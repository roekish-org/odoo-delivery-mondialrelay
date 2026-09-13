# Copyright 2026 ROEKISH
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import hashlib
import logging
import re
import unicodedata

import requests
from lxml import etree

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    from zeep import Client as ZeepClient
except ImportError:  # pragma: no cover - zeep is an optional dependency
    ZeepClient = None
    _logger.debug("Cannot `import zeep`; Mondial Relay Point Relais search disabled.")

# Mondial Relay Web Service (API V1, SOAP): Point Relais search.
SEARCH_WSDL = "https://api.mondialrelay.com/Web_Services.asmx?WSDL"
# Mondial Relay Connect API (API V2, XML over HTTPS): shipment and label
# creation. The sandbox accepts the same credentials as production once
# Mondial Relay has enabled them for tests.
CONNECT_URL = "https://connect-api.mondialrelay.com/api/shipment"
CONNECT_SANDBOX_URL = "https://connect-api-sandbox.mondialrelay.com/api/shipment"
CONNECT_NS = "http://www.example.org/Request"
CONNECT_TIMEOUT = 30
# Order of the WSI4_PointRelais_Recherche parameters in the security hash.
SEARCH_HASH_KEYS = (
    "Enseigne",
    "Pays",
    "NumPointRelais",
    "Ville",
    "CP",
    "Latitude",
    "Longitude",
    "Taille",
    "Poids",
    "Action",
    "DelaiEnvoi",
    "RayonRecherche",
    "TypeActivite",
    "NombreResultats",
)
# Meaning of the STAT codes the search can return (subset of the documented
# list; other codes are surfaced with their number).
SEARCH_STATUSES = {
    "1": "Invalid merchant code",
    "8": "Invalid password or hash",
    "9": "City not recognised or not unique",
    "20": "Invalid parcel weight",
    "36": "Invalid ZIP code",
    "37": "Invalid country",
    "70": "Invalid Point Relais number",
    "93": "No Point Relais available around this address",
    "95": "Merchant account not activated",
    "97": "Invalid security key",
    "98": "Generic error (invalid parameters)",
    "99": "Generic web service error",
}
# Mondial Relay carries parcels up to 30 kg (20 kg for a Locker).
MAX_WEIGHT = {"24R": 30.0, "24L": 20.0, "HOM": 30.0, "LCC": 30.0}
# Mondial Relay serves France and a set of European countries.
FR_COUNTRY_CODES = {"FR", "MC"}
EU1_COUNTRY_CODES = {"BE", "LU", "NL", "DE"}
EU2_COUNTRY_CODES = {"ES", "GB"}
EU3_COUNTRY_CODES = {"IT", "PT", "AT"}
# Point Relais delivery is available in France and in these countries only.
PICKUP_COUNTRY_CODES = FR_COUNTRY_CODES | {"BE", "LU", "NL", "ES", "PT"}


class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    delivery_type = fields.Selection(
        selection_add=[("mondialrelay", "Mondial Relay")],
        ondelete={"mondialrelay": "set default"},
    )
    mondialrelay_merchant = fields.Char(
        string="Merchant code",
        help="Code Enseigne provided by Mondial Relay (8 characters, for "
        "example BDTEST13 for the public test account).",
    )
    mondialrelay_private_key = fields.Char(
        string="Web service private key",
        groups="roekish_delivery_mondialrelay.group_mondialrelay_manager",
        help="Private key of the Mondial Relay Web Service (API V1), used to "
        "sign Point Relais searches. Readable only by Mondial Relay "
        "administrators.",
    )
    mondialrelay_api_login = fields.Char(
        string="Connect API login",
        groups="roekish_delivery_mondialrelay.group_mondialrelay_manager",
        help="Login of the Mondial Relay Connect API (API V2) account used to "
        "create shipments and labels.",
    )
    mondialrelay_api_password = fields.Char(
        string="Connect API password",
        groups="roekish_delivery_mondialrelay.group_mondialrelay_manager",
        help="Password of the Mondial Relay Connect API account. Readable only "
        "by Mondial Relay administrators.",
    )
    mondialrelay_sandbox = fields.Boolean(
        string="Sandbox",
        help="Create shipments on the Mondial Relay Connect API sandbox "
        "instead of production.",
    )
    mondialrelay_delivery_mode = fields.Selection(
        selection=[
            ("24R", "Point Relais"),
            ("24L", "Point Relais XL / Locker"),
            ("HOM", "Home delivery"),
            ("LCC", "Delivery at the merchant"),
        ],
        string="Delivery mode",
        default="24R",
        help="Mondial Relay delivery mode sent on the shipment.",
    )
    mondialrelay_collection_mode = fields.Selection(
        selection=[
            ("CCC", "Collected at the merchant"),
            ("REL", "Dropped in a Point Relais"),
        ],
        string="Collection mode",
        default="CCC",
        help="How the parcel enters the Mondial Relay network.",
    )
    mondialrelay_label_format = fields.Selection(
        selection=[
            ("10x15", "PDF 10x15"),
            ("A4", "PDF A4"),
            ("A5", "PDF A5"),
            ("ZPL", "ZPL 10x15 (label printer)"),
        ],
        string="Label format",
        default="10x15",
    )
    mondialrelay_pricing_method = fields.Selection(
        selection=[
            ("grid", "Mondial Relay tariff grid"),
            ("base_on_rule", "Odoo pricing rules"),
        ],
        string="Pricing method",
        default="grid",
        help="How the delivery price is computed:\n"
        "- Mondial Relay tariff grid: weight x destination zone lines defined "
        "on this carrier.\n"
        "- Odoo pricing rules: the standard rule-based pricing engine.",
    )
    mondialrelay_tariff_ids = fields.One2many(
        "delivery.mondialrelay.tariff",
        "carrier_id",
        string="Mondial Relay tariff grid",
    )
    mondialrelay_delay_min = fields.Integer(
        string="Delivery days min",
        help="Shortest delivery time announced by Mondial Relay, in working days "
        "after hand-over. Applies to every destination unless a tariff grid "
        "line overrides it. Leave 0 when unknown.",
    )
    mondialrelay_delay_max = fields.Integer(
        string="Delivery days max",
        help="Longest delivery time announced by Mondial Relay, in working days "
        "after hand-over. Applies to every destination unless a tariff grid "
        "line overrides it. Leave 0 when unknown.",
    )

    # ------------------------------------------------------------------
    # Rating
    # ------------------------------------------------------------------
    def mondialrelay_rate_shipment(self, order):
        """Return a delivery quote for ``order`` (sale.order).

        On success the dict also carries ``delay_min`` and ``delay_max``
        (working days, 0 when unknown) so carriers can be compared on cost
        and speed. See ``_mondialrelay_with_delay``.
        """
        self.ensure_one()
        country = order.partner_shipping_id.country_id
        weight = order._get_estimated_weight()
        error = self._mondialrelay_check_destination(country, weight)
        if error:
            return {
                "success": False,
                "price": 0.0,
                "error_message": error,
                "warning_message": False,
            }
        zone = self._mondialrelay_get_zone(country)
        # Extension point for a live rating endpoint. Mondial Relay exposes
        # none, so this returns None and we fall back to the configured
        # pricing method. Any override MUST fail closed (return None).
        price = self._mondialrelay_get_live_price(order)
        if price is None and self.mondialrelay_pricing_method == "base_on_rule":
            return self._mondialrelay_with_delay(
                self.base_on_rule_rate_shipment(order), zone, weight
            )
        if price is None:
            price = self._mondialrelay_grid_rate(zone, weight)
        if price is None:
            return {
                "success": False,
                "price": 0.0,
                "error_message": self.env._(
                    "No Mondial Relay tariff matches this destination and "
                    "weight. Add a matching line to the tariff grid of "
                    "carrier '%s'.",
                    self.name,
                ),
                "warning_message": False,
            }
        return self._mondialrelay_with_delay(
            {
                "success": True,
                "price": price,
                "error_message": False,
                "warning_message": False,
            },
            zone,
            weight,
        )

    def _mondialrelay_get_live_price(self, order):
        """Hook for a future Mondial Relay live-pricing web call.

        Mondial Relay does not expose a rating API today, so this returns
        None and pricing falls back to the tariff grid or Odoo rules.
        Override to plug a real endpoint; keep it fail-closed.
        """
        return None

    def _mondialrelay_grid_line(self, zone, weight):
        """Return the first tariff grid line covering ``zone`` and ``weight``."""
        self.ensure_one()
        if not zone:
            return self.env["delivery.mondialrelay.tariff"]
        return self.env["delivery.mondialrelay.tariff"].search(
            [
                ("carrier_id", "=", self.id),
                ("zone", "=", zone),
                ("max_weight", ">=", weight),
            ],
            order="max_weight asc",
            limit=1,
        )

    def _mondialrelay_grid_rate(self, zone, weight):
        """Look up the price for ``zone`` and ``weight`` in the tariff grid.

        Returns the price (company currency) or None when no bracket matches.
        """
        line = self._mondialrelay_grid_line(zone, weight)
        return line.price if line else None

    def _mondialrelay_get_delay(self, zone, weight):
        """Announced delivery time for a shipment, as (min, max) working days.

        The tariff grid line covering the shipment overrides the carrier
        values; 0 means unknown.
        """
        self.ensure_one()
        line = self.env["delivery.mondialrelay.tariff"]
        if self.mondialrelay_pricing_method == "grid":
            line = self._mondialrelay_grid_line(zone, weight)
        return (
            line.delay_min or self.mondialrelay_delay_min,
            line.delay_max or self.mondialrelay_delay_max,
        )

    def _mondialrelay_with_delay(self, res, zone, weight):
        """Add the delivery time to a successful quote.

        ``delay_min`` / ``delay_max`` (working days, 0 = unknown) let a caller
        compare carriers on cost and speed. The readable sentence rides
        ``warning_message``, which the shipping wizard displays and the sale
        order stores as ``delivery_message``; an existing warning is kept.
        """
        if not res.get("success"):
            return res
        delay_min, delay_max = self._mondialrelay_get_delay(zone, weight)
        res.update(delay_min=delay_min, delay_max=delay_max)
        if not res.get("warning_message"):
            res["warning_message"] = self._mondialrelay_delay_message(
                delay_min, delay_max
            )
        return res

    @api.model
    def _mondialrelay_delay_message(self, delay_min, delay_max):
        """Human-readable delivery time, False when unknown."""
        if delay_min and delay_max and delay_min != delay_max:
            return self.env._(
                "Delivery in %(min)s to %(max)s working days.",
                min=delay_min,
                max=delay_max,
            )
        days = delay_max or delay_min
        if days == 1:
            return self.env._("Delivery in 1 working day.")
        if days:
            return self.env._("Delivery in %s working days.", days)
        return False

    @api.model
    def _mondialrelay_get_zone(self, country):
        """Map a destination country to a Mondial Relay pricing zone.

        Returns False for countries Mondial Relay does not serve.
        """
        code = country.code if country else None
        if not code or code in FR_COUNTRY_CODES:
            return "FR"
        if code in EU1_COUNTRY_CODES:
            return "EU1"
        if code in EU2_COUNTRY_CODES:
            return "EU2"
        if code in EU3_COUNTRY_CODES:
            return "EU3"
        return False

    def _mondialrelay_check_destination(self, country, weight):
        """Return an error message when Mondial Relay cannot serve the shipment."""
        code = country.code if country else "FR"
        if not self._mondialrelay_get_zone(country):
            return self.env._(
                "Mondial Relay does not deliver to %s.", country.display_name
            )
        mode = self.mondialrelay_delivery_mode
        if mode in ("24R", "24L") and code not in PICKUP_COUNTRY_CODES:
            return self.env._(
                "Mondial Relay Point Relais delivery is not available in %s: "
                "use a home delivery carrier.",
                country.display_name,
            )
        limit = MAX_WEIGHT.get(mode, 30.0)
        if weight > limit:
            return self.env._(
                "Mondial Relay is limited to %s kg per parcel for this delivery mode.",
                limit,
            )
        return False

    # ------------------------------------------------------------------
    # Shipping (label generation, Connect API V2)
    # ------------------------------------------------------------------
    def mondialrelay_send_shipping(self, pickings):
        """Create one Mondial Relay shipment per picking."""
        self.ensure_one()
        return [self._mondialrelay_send_one(picking) for picking in pickings]

    def _mondialrelay_send_one(self, picking):
        self.ensure_one()
        body = self._mondialrelay_build_request(picking)
        root = self._mondialrelay_post(body)
        shipment = root.find(".//ShipmentsList/Shipment")
        if shipment is None:
            raise UserError(
                self.env._("Mondial Relay returned no shipment for %s.", picking.name)
            )
        self._mondialrelay_raise_for_statuses(shipment.findall("StatusList/Status"))
        number = shipment.get("ShipmentNumber") or ""
        output = (shipment.findtext("LabelList/Label/Output") or "").strip()
        self._mondialrelay_attach_label(picking, number, output)
        return {
            "exact_price": self._mondialrelay_price_for_picking(picking),
            "tracking_number": number or False,
        }

    def _mondialrelay_attach_label(self, picking, number, output):
        """Attach the label (PDF fetched from its URL, or raw ZPL code)."""
        if not output:
            raise UserError(
                self.env._("Mondial Relay returned no label for shipment %s.", number)
            )
        base = "%s_%s" % (picking.name.replace("/", "_"), number)
        if self.mondialrelay_label_format == "ZPL":
            attachments = [("%s.zpl" % base, output.encode("utf-8"))]
        else:
            try:
                response = requests.get(output, timeout=CONNECT_TIMEOUT)
                response.raise_for_status()
            except requests.RequestException as exc:
                _logger.exception("Mondial Relay label download failed")
                raise UserError(
                    self.env._(
                        "The Mondial Relay label could not be downloaded:\n%s",
                        self._mondialrelay_mask_secrets(str(exc)),
                    )
                ) from exc
            attachments = [("%s.pdf" % base, response.content)]
        picking.message_post(
            body=self.env._("Mondial Relay label %s", number),
            attachments=attachments,
        )

    def _mondialrelay_price_for_picking(self, picking):
        """Best-effort delivery price for the confirmation of a shipment."""
        self.ensure_one()
        price = self._mondialrelay_grid_rate(
            self._mondialrelay_get_zone(picking.partner_id.country_id),
            picking.shipping_weight or picking.weight or 0.0,
        )
        return price if price is not None else 0.0

    def _mondialrelay_build_request(self, picking):
        """Build the ShipmentCreationRequest XML for one picking."""
        self.ensure_one()
        self._mondialrelay_check_shipment(picking)
        creds = self.sudo()
        company = self.company_id or self.env.company
        partner = picking.partner_id
        weight = picking.shipping_weight or picking.weight or 0.0
        mode = self.mondialrelay_delivery_mode
        location = ""
        if mode in ("24R", "24L"):
            location = "%s-%s" % (
                picking.mondialrelay_pickup_point_country or partner.country_id.code,
                picking.mondialrelay_pickup_point_code,
            )

        root = etree.Element("ShipmentCreationRequest", xmlns=CONNECT_NS)
        context = etree.SubElement(root, "Context")
        self._mondialrelay_text(context, "Login", creds.mondialrelay_api_login)
        self._mondialrelay_text(context, "Password", creds.mondialrelay_api_password)
        self._mondialrelay_text(context, "CustomerId", self.mondialrelay_merchant)
        self._mondialrelay_text(context, "Culture", "fr-FR")
        self._mondialrelay_text(context, "VersionAPI", "1.0")
        options = etree.SubElement(root, "OutputOptions")
        if self.mondialrelay_label_format == "ZPL":
            self._mondialrelay_text(options, "OutputFormat", "Generic_ZPL_10x15_200dpi")
            self._mondialrelay_text(options, "OutputType", "ZplCode")
        else:
            self._mondialrelay_text(
                options, "OutputFormat", self.mondialrelay_label_format
            )
            self._mondialrelay_text(options, "OutputType", "PdfUrl")
        shipments = etree.SubElement(root, "ShipmentsList")
        shipment = etree.SubElement(shipments, "Shipment")
        self._mondialrelay_text(
            shipment,
            "OrderNo",
            self._mondialrelay_reference(
                picking.sale_id.name or picking.origin or picking.name
            ),
        )
        self._mondialrelay_text(
            shipment, "CustomerNo", self._mondialrelay_reference(partner.ref or "", 9)
        )
        self._mondialrelay_text(shipment, "ParcelCount", "1")
        etree.SubElement(shipment, "DeliveryMode", Mode=mode, Location=location)
        etree.SubElement(
            shipment,
            "CollectionMode",
            Mode=self.mondialrelay_collection_mode,
            Location="",
        )
        parcels = etree.SubElement(shipment, "Parcels")
        parcel = etree.SubElement(parcels, "Parcel")
        self._mondialrelay_text(parcel, "Content", picking.name)
        etree.SubElement(
            parcel, "Weight", Value=str(int(round(weight * 1000))), Unit="gr"
        )
        self._mondialrelay_address(
            etree.SubElement(shipment, "Sender"), company.partner_id
        )
        self._mondialrelay_address(etree.SubElement(shipment, "Recipient"), partner)
        return etree.tostring(root, xml_declaration=True, encoding="utf-8")

    @api.model
    def _mondialrelay_text(self, parent, tag, value):
        node = etree.SubElement(parent, tag)
        node.text = value or ""
        return node

    @api.model
    def _mondialrelay_reference(self, value, size=15):
        """Mondial Relay references: upper-case alphanumeric, dash, underscore."""
        text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore")
        return re.sub(r"[^0-9A-Z_-]", "", text.decode().upper().replace(" ", "_"))[
            :size
        ]

    @api.model
    def _mondialrelay_address(self, parent, partner):
        """Fill an <Address> block from a res.partner."""
        address = etree.SubElement(parent, "Address")
        if partner.is_company or not partner.name:
            firstname, lastname = "", partner.name or ""
        else:
            parts = partner.name.split(" ", 1)
            firstname, lastname = (
                (parts[0], parts[1]) if len(parts) > 1 else ("", parts[0])
            )
        company = partner.commercial_company_name or ""
        phone = partner.phone or ""
        mobile = (
            phone
            if re.match(
                r"^(?:\+336|\+337|00336|00337|06|07)", re.sub(r"[\s.\-()]", "", phone)
            )
            else ""
        )
        for tag, value in (
            ("Title", ""),
            ("Firstname", firstname[:32]),
            ("Lastname", lastname[:32]),
            ("Streetname", (partner.street or "")[:40]),
            ("HouseNo", ""),
            ("CountryCode", partner.country_id.code or ""),
            ("PostCode", partner.zip or ""),
            ("City", (partner.city or "")[:30]),
            ("AddressAdd1", (partner.street2 or "")[:40]),
            ("AddressAdd2", company[:40] if company != partner.name else ""),
            ("AddressAdd3", ""),
            ("PhoneNo", phone),
            ("MobileNo", mobile),
            ("Email", partner.email or ""),
        ):
            self._mondialrelay_text(address, tag, value)
        return address

    def _mondialrelay_check_shipment(self, picking):
        """Fail closed, with a clear message, before calling Mondial Relay."""
        partner = picking.partner_id
        weight = picking.shipping_weight or picking.weight or 0.0
        if weight <= 0:
            raise UserError(
                self.env._(
                    "Set a shipping weight on %s before generating a Mondial "
                    "Relay label.",
                    picking.name,
                )
            )
        error = self._mondialrelay_check_destination(partner.country_id, weight)
        if error:
            raise UserError(error)
        if not self.mondialrelay_merchant:
            raise UserError(
                self.env._(
                    "Fill the Mondial Relay merchant code on carrier '%s' first.",
                    self.name,
                )
            )
        missing = [
            partner._fields[name].string
            for name in ("street", "zip", "city", "country_id")
            if not partner[name]
        ]
        if missing:
            raise UserError(
                self.env._(
                    "The delivery address of %(picking)s is incomplete "
                    "(missing: %(fields)s).",
                    picking=picking.name,
                    fields=", ".join(missing),
                )
            )
        mode = self.mondialrelay_delivery_mode
        if mode in ("24R", "24L") and not picking.mondialrelay_pickup_point_code:
            raise UserError(
                self.env._(
                    "Choose a Point Relais on %s before generating a Mondial "
                    "Relay label.",
                    picking.name,
                )
            )
        if mode == "HOM" and not partner.phone:
            raise UserError(
                self.env._(
                    "Mondial Relay home delivery requires a phone number on "
                    "the recipient %s.",
                    partner.display_name,
                )
            )
        if not (partner.phone or partner.email):
            raise UserError(
                self.env._(
                    "Mondial Relay requires a phone number or an email on the "
                    "recipient %s.",
                    partner.display_name,
                )
            )
        company = self.company_id or self.env.company
        sender = company.partner_id
        if not (sender.street and sender.zip and sender.city and sender.country_id):
            raise UserError(
                self.env._(
                    "Complete the address of company %s: it is the parcel sender.",
                    company.name,
                )
            )

    # ------------------------------------------------------------------
    # Connect API client
    # ------------------------------------------------------------------
    def _mondialrelay_post(self, body):
        """POST a ShipmentCreationRequest, return the parsed response root.

        Any transport error or critical status is turned into a UserError
        carrying Mondial Relay's own message, with the secrets redacted.
        """
        self.ensure_one()
        creds = self.sudo()
        if not (creds.mondialrelay_api_login and creds.mondialrelay_api_password):
            raise UserError(
                self.env._(
                    "Fill the Mondial Relay Connect API login and password on "
                    "carrier '%s' first.",
                    self.name,
                )
            )
        url = CONNECT_SANDBOX_URL if self.mondialrelay_sandbox else CONNECT_URL
        try:
            response = requests.post(
                url,
                data=body,
                headers={"Content-Type": "text/xml", "Accept": "application/xml"},
                timeout=CONNECT_TIMEOUT,
            )
            response.raise_for_status()
            # Namespaces carry no information here: strip them for lookups.
            xml = re.sub(rb'\sxmlns(:\w+)?="[^"]*"', b"", response.content)
            root = etree.fromstring(xml)
        except Exception as exc:
            _logger.exception("Mondial Relay request failed")
            raise UserError(
                self.env._(
                    "Mondial Relay is unreachable or answered unexpectedly:\n%s",
                    self._mondialrelay_mask_secrets(str(exc)),
                )
            ) from exc
        self._mondialrelay_raise_for_statuses(root.findall("StatusList/Status"))
        return root

    def _mondialrelay_raise_for_statuses(self, statuses):
        """Raise on any status at Error or Critical level."""
        errors = [
            "%s (code %s)" % (status.get("Message", ""), status.get("Code", ""))
            for status in statuses
            if "error" in (status.get("Level") or "").lower()
        ]
        if errors:
            raise UserError(
                self.env._(
                    "Mondial Relay rejected the request:\n%s",
                    self._mondialrelay_mask_secrets("\n".join(errors)),
                )
            )

    def _mondialrelay_mask_secrets(self, text):
        self.ensure_one()
        if not text:
            return text
        creds = self.sudo()
        for secret in (creds.mondialrelay_api_password, creds.mondialrelay_private_key):
            if secret:
                text = text.replace(secret, "****")
        return re.sub(
            r"(<Password>).*?(</Password>)", r"\1****\2", text, flags=re.DOTALL
        )

    # ------------------------------------------------------------------
    # Connectivity test (go-live check)
    # ------------------------------------------------------------------
    def action_mondialrelay_test_connection(self):
        """Check both credentials without creating anything.

        The Point Relais search is called on the company address (Web
        Service private key), then an empty shipment list is posted to the
        Connect API, which validates the login and password without creating
        a shipment.
        """
        self.ensure_one()
        creds = self.sudo()
        if not (self.mondialrelay_merchant and creds.mondialrelay_private_key):
            raise UserError(
                self.env._(
                    "Fill the merchant code and the web service private key "
                    "before testing the connection."
                )
            )
        company_partner = (self.company_id or self.env.company).partner_id
        points = self._mondialrelay_call_search_ws(
            company_partner.zip or "75001",
            company_partner.city or "Paris",
            company_partner.country_id.code or "FR",
            1.0,
        )
        root = etree.Element("ShipmentCreationRequest", xmlns=CONNECT_NS)
        context = etree.SubElement(root, "Context")
        self._mondialrelay_text(context, "Login", creds.mondialrelay_api_login)
        self._mondialrelay_text(context, "Password", creds.mondialrelay_api_password)
        self._mondialrelay_text(context, "CustomerId", self.mondialrelay_merchant)
        self._mondialrelay_text(context, "Culture", "fr-FR")
        self._mondialrelay_text(context, "VersionAPI", "1.0")
        etree.SubElement(root, "ShipmentsList")
        self._mondialrelay_post(
            etree.tostring(root, xml_declaration=True, encoding="utf-8")
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Mondial Relay"),
                "message": self.env._(
                    "Connection successful, %s Points Relais returned and the "
                    "Connect API accepted the credentials.",
                    len(points),
                ),
                "type": "success",
                "sticky": False,
            },
        }

    # ------------------------------------------------------------------
    # Point Relais search (Web Service API V1)
    # ------------------------------------------------------------------
    def _mondialrelay_search_pickup_points(self, zipcode, city, country_code, weight):
        """Return a list of Points Relais near ``zipcode``.

        Each item is a dict: code, name, street, zip, city, country, distance.
        When the merchant code and private key are set, the live Mondial
        Relay web service is queried; otherwise demonstrative points are
        returned so the flow stays testable without an account.
        """
        self.ensure_one()
        if self.mondialrelay_merchant and self.sudo().mondialrelay_private_key:
            return self._mondialrelay_call_search_ws(
                zipcode, city, country_code, weight
            )
        return self._mondialrelay_demo_pickup_points(zipcode, city, country_code)

    def _mondialrelay_sign(self, params):
        """Security hash: MD5 of the non-empty parameters + private key."""
        self.ensure_one()
        private_key = self.sudo().mondialrelay_private_key or ""
        chain = "".join(str(params.get(key) or "") for key in SEARCH_HASH_KEYS)
        chain = unicodedata.normalize("NFKD", chain).encode("ascii", "ignore")
        return hashlib.md5(chain + private_key.encode("latin-1")).hexdigest().upper()

    def _mondialrelay_call_search_ws(self, zipcode, city, country_code, weight):
        self.ensure_one()
        if ZeepClient is None:
            raise UserError(
                self.env._(
                    "The Python library 'zeep' is required to search Mondial "
                    "Relay Points Relais. Install it with: pip install zeep"
                )
            )
        params = {
            "Enseigne": self.mondialrelay_merchant,
            "Pays": (country_code or "FR").upper(),
            "NumPointRelais": "",
            "Ville": "",
            "CP": zipcode or "",
            "Latitude": "",
            "Longitude": "",
            "Taille": "",
            "Poids": str(int((weight or 0) * 1000)) if weight else "",
            "Action": (
                self.mondialrelay_delivery_mode
                if self.mondialrelay_delivery_mode in ("24R", "24L")
                else "24R"
            ),
            "DelaiEnvoi": "0",
            "RayonRecherche": "",
            "TypeActivite": "",
            "NombreResultats": "10",
        }
        params["Security"] = self._mondialrelay_sign(params)
        try:
            client = ZeepClient(SEARCH_WSDL)
            response = client.service.WSI4_PointRelais_Recherche(**params)
        except Exception as exc:
            _logger.exception("Mondial Relay Point Relais search failed")
            raise UserError(
                self.env._(
                    "Mondial Relay Point Relais search failed:\n%s",
                    self._mondialrelay_mask_secrets(str(exc)),
                )
            ) from exc
        # Mondial Relay returns STAT 0 on success; errors come back in the
        # body (no SOAP fault), so they must be checked explicitly.
        stat = str(getattr(response, "STAT", "") or "")
        if stat != "0":
            raise UserError(
                self.env._(
                    "Mondial Relay refused the request (code %(code)s): %(msg)s",
                    code=stat,
                    msg=SEARCH_STATUSES.get(stat, "error %s" % stat),
                )
            )
        details = getattr(response, "PointsRelais", None)
        details = getattr(details, "PointRelais_Details", None) or []
        points = []
        for point in details:
            name = " ".join(
                filter(
                    None,
                    [
                        (getattr(point, "LgAdr1", "") or "").strip(),
                        (getattr(point, "LgAdr2", "") or "").strip(),
                    ],
                )
            )
            street = " ".join(
                filter(
                    None,
                    [
                        (getattr(point, "LgAdr3", "") or "").strip(),
                        (getattr(point, "LgAdr4", "") or "").strip(),
                    ],
                )
            )
            points.append(
                {
                    "code": getattr(point, "Num", "") or "",
                    "name": name,
                    "street": street,
                    "zip": getattr(point, "CP", "") or "",
                    "city": (getattr(point, "Ville", "") or "").strip(),
                    "country": getattr(point, "Pays", "") or "",
                    "distance": float(getattr(point, "Distance", 0) or 0),
                }
            )
        return points

    @api.model
    def _mondialrelay_demo_pickup_points(self, zipcode, city, country_code="FR"):
        zipcode = zipcode or "75001"
        city = city or "Paris"
        country_code = country_code or "FR"
        return [
            {
                "code": "010001",
                "name": "Point Relais Presse %s" % city,
                "street": "1 rue de la Republique",
                "zip": zipcode,
                "city": city,
                "country": country_code,
                "distance": 140.0,
            },
            {
                "code": "010002",
                "name": "Point Relais Fleuriste %s" % city,
                "street": "12 avenue des Colis",
                "zip": zipcode,
                "city": city,
                "country": country_code,
                "distance": 390.0,
            },
            {
                "code": "010003",
                "name": "Locker Mondial Relay",
                "street": "3 place du Marche",
                "zip": zipcode,
                "city": city,
                "country": country_code,
                "distance": 620.0,
            },
        ]

    # ------------------------------------------------------------------
    # Tracking & cancellation
    # ------------------------------------------------------------------
    def mondialrelay_get_tracking_link(self, picking):
        self.ensure_one()
        ref = (picking.carrier_tracking_ref or "").split(",")[0].strip()
        return (
            "https://www.mondialrelay.fr/suivi-de-colis/?numeroExpedition=%s"
            "&codePostal=%s" % (ref, picking.partner_id.zip or "")
        )

    def mondialrelay_cancel_shipment(self, pickings):
        """Clear the tracking reference.

        Mondial Relay exposes no shipment-cancellation web service: an unused
        label simply expires. Reset Odoo state and remind the user.
        """
        self.ensure_one()
        for picking in pickings:
            picking.message_post(
                body=self.env._(
                    "Mondial Relay tracking reference cleared in Odoo. If the "
                    "parcel was already handed over, contact Mondial Relay."
                )
            )
            picking.carrier_tracking_ref = False
        return True

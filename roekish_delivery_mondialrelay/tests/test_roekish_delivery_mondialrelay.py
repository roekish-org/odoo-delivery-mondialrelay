# Copyright 2026 ROEKISH
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import hashlib
from types import SimpleNamespace
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

CARRIER_MODULE = "odoo.addons.roekish_delivery_mondialrelay.models.delivery_carrier"

RESPONSE_NS = 'xmlns="http://www.example.org/Response"'
CREATED_XML = (
    "<ShipmentCreationResponse %s><StatusList /><ShipmentsList>"
    '<Shipment ShipmentNumber="12345678"><StatusList /><LabelList><Label>'
    "<Output>%s</Output></Label></LabelList></Shipment></ShipmentsList>"
    "</ShipmentCreationResponse>"
)
EMPTY_XML = (
    "<ShipmentCreationResponse %s><StatusList /></ShipmentCreationResponse>"
    % RESPONSE_NS
)
LOGIN_ERROR_XML = (
    '<ShipmentCreationResponse %s><StatusList><Status Code="10001" '
    'Level="Critical error" Message="Login et/ou mot de passe non valide." />'
    "</StatusList></ShipmentCreationResponse>" % RESPONSE_NS
)


class FakeResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("HTTP %s" % self.status_code)


class TestDeliveryMondialrelay(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.partner_id.write(
            {
                "street": "26 rue George Sand",
                "zip": "75016",
                "city": "Paris",
                "country_id": cls.env.ref("base.fr").id,
                "phone": "+33 1 23 45 67 89",
            }
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Mondial Relay", "type": "service"}
        )
        common = {
            "delivery_type": "mondialrelay",
            "product_id": cls.product.id,
            "mondialrelay_merchant": "BDTEST13",
            "mondialrelay_private_key": "TestAPI1key",
            "mondialrelay_api_login": "api@example.com",
            "mondialrelay_api_password": "S3cret!",
            "mondialrelay_pricing_method": "grid",
        }
        cls.relay_carrier = cls.env["delivery.carrier"].create(
            dict(common, name="MR Relais Test", mondialrelay_delivery_mode="24R")
        )
        cls.home_carrier = cls.env["delivery.carrier"].create(
            dict(common, name="MR Domicile Test", mondialrelay_delivery_mode="HOM")
        )
        cls.env["delivery.mondialrelay.tariff"].create(
            [
                {
                    "carrier_id": cls.relay_carrier.id,
                    "zone": "FR",
                    "max_weight": 1.0,
                    "price": 5.99,
                },
                {
                    "carrier_id": cls.relay_carrier.id,
                    "zone": "FR",
                    "max_weight": 3.0,
                    "price": 7.99,
                },
                {
                    "carrier_id": cls.home_carrier.id,
                    "zone": "FR",
                    "max_weight": 2.0,
                    "price": 10.99,
                },
                {
                    "carrier_id": cls.home_carrier.id,
                    "zone": "EU1",
                    "max_weight": 30.0,
                    "price": 30.40,
                },
            ]
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _create_order(self, carrier, weight=1.2, partner_vals=None):
        vals = {
            "name": "Marie Dupont",
            "street": "27 Rue Henri Rolland",
            "zip": "69100",
            "city": "Villeurbanne",
            "phone": "06 12 34 56 78",
            "email": "marie@example.com",
            "country_id": self.env.ref("base.fr").id,
        }
        vals.update(partner_vals or {})
        partner = self.env["res.partner"].create(vals)
        product = self.env["product.product"].create(
            {"name": "Boxed", "is_storable": True, "weight": weight}
        )
        return self.env["sale.order"].create(
            {
                "partner_id": partner.id,
                "carrier_id": carrier.id,
                "order_line": [
                    (0, 0, {"product_id": product.id, "product_uom_qty": 1})
                ],
            }
        )

    def _create_delivery(self, carrier, pickup=True, **kwargs):
        order = self._create_order(carrier, **kwargs)
        if pickup and carrier.mondialrelay_delivery_mode in ("24R", "24L"):
            order.write(
                {
                    "mondialrelay_pickup_point_code": "010001",
                    "mondialrelay_pickup_point_name": "Presse Lyon",
                    "mondialrelay_pickup_point_country": "FR",
                }
            )
        order.action_confirm()
        picking = order.picking_ids[:1]
        self.assertTrue(picking, "a delivery order should have been created")
        return picking

    # ------------------------------------------------------------------
    # zones and rating
    # ------------------------------------------------------------------
    def test_zone_mapping(self):
        get_zone = self.relay_carrier._mondialrelay_get_zone
        self.assertEqual(get_zone(self.env.ref("base.fr")), "FR")
        self.assertEqual(get_zone(self.env.ref("base.be")), "EU1")
        self.assertEqual(get_zone(self.env.ref("base.es")), "EU2")
        self.assertEqual(get_zone(self.env.ref("base.it")), "EU3")
        self.assertFalse(get_zone(self.env.ref("base.us")))
        self.assertEqual(get_zone(self.env["res.country"]), "FR")

    def test_grid_rate_bracket(self):
        self.assertEqual(self.relay_carrier._mondialrelay_grid_rate("FR", 0.8), 5.99)
        self.assertEqual(self.relay_carrier._mondialrelay_grid_rate("FR", 2.5), 7.99)
        self.assertIsNone(self.relay_carrier._mondialrelay_grid_rate("FR", 10.0))
        self.assertIsNone(self.relay_carrier._mondialrelay_grid_rate(False, 1.0))

    def test_rate_shipment_success(self):
        res = self.relay_carrier.mondialrelay_rate_shipment(
            self._create_order(self.relay_carrier)
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["price"], 7.99)
        res = self.home_carrier.mondialrelay_rate_shipment(
            self._create_order(
                self.home_carrier,
                partner_vals={"country_id": self.env.ref("base.be").id},
            )
        )
        self.assertEqual(res["price"], 30.40)

    def test_rate_shipment_refuses_unserved_country_and_heavy_parcels(self):
        res = self.relay_carrier.mondialrelay_rate_shipment(
            self._create_order(
                self.relay_carrier,
                partner_vals={"country_id": self.env.ref("base.us").id},
            )
        )
        self.assertFalse(res["success"])
        self.assertIn("does not deliver", res["error_message"])
        # Point Relais delivery exists in Belgium but not in Germany.
        res = self.relay_carrier.mondialrelay_rate_shipment(
            self._create_order(
                self.relay_carrier,
                partner_vals={"country_id": self.env.ref("base.de").id},
            )
        )
        self.assertIn("Point Relais", res["error_message"])
        res = self.relay_carrier.mondialrelay_rate_shipment(
            self._create_order(self.relay_carrier, weight=31.0)
        )
        self.assertIn("30", res["error_message"])

    def test_rate_shipment_base_on_rule(self):
        self.relay_carrier.write(
            {
                "mondialrelay_pricing_method": "base_on_rule",
                "price_rule_ids": [
                    (
                        0,
                        0,
                        {
                            "variable": "weight",
                            "operator": ">=",
                            "max_value": 0.0,
                            "list_base_price": 4.5,
                        },
                    )
                ],
            }
        )
        res = self.relay_carrier.mondialrelay_rate_shipment(
            self._create_order(self.relay_carrier)
        )
        self.assertEqual(res["price"], 4.5)

    # ------------------------------------------------------------------
    # Points Relais
    # ------------------------------------------------------------------
    def test_is_pickup_compute(self):
        self.assertTrue(self._create_order(self.relay_carrier).mondialrelay_is_pickup)
        self.assertFalse(self._create_order(self.home_carrier).mondialrelay_is_pickup)

    def test_demo_pickup_points(self):
        self.relay_carrier.mondialrelay_private_key = False
        points = self.relay_carrier._mondialrelay_search_pickup_points(
            "75001", "Paris", "FR", 1.0
        )
        self.assertEqual(len(points), 3)
        self.assertEqual(points[0]["zip"], "75001")
        self.assertEqual(points[0]["country"], "FR")

    def test_security_hash_matches_documentation(self):
        # Example of the Mondial Relay documentation: BDTEST13 + 12345678 + FR
        # + TestAPI1key -> 33DA5F122DAA40241087CC7845BEA4B1. The same
        # algorithm applies to every method, keyed on the search parameters.
        expected = hashlib.md5(b"BDTEST13FR69001100024R010TestAPI1key").hexdigest()
        params = {
            "Enseigne": "BDTEST13",
            "Pays": "FR",
            "CP": "69001",
            "Poids": "1000",
            "Action": "24R",
            "DelaiEnvoi": "0",
            "NombreResultats": "10",
        }
        self.assertEqual(
            self.relay_carrier._mondialrelay_sign(params), expected.upper()
        )

    def test_pickup_ws_as_plain_user_and_stat_code(self):
        user = self.env["res.users"].create(
            {
                "name": "Ops",
                "login": "ops_mr",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            self.env.ref(
                                "roekish_delivery_mondialrelay.group_mondialrelay_user"
                            ).id
                        ],
                    )
                ],
            }
        )
        carrier = self.relay_carrier.with_user(user)
        with patch(CARRIER_MODULE + ".ZeepClient") as zeep_client:
            call = zeep_client.return_value.service.WSI4_PointRelais_Recherche
            call.return_value = SimpleNamespace(STAT="97", PointsRelais=None)
            with self.assertRaises(UserError) as ctx:
                carrier._mondialrelay_search_pickup_points("69001", "Lyon", "FR", 1.0)
            self.assertIn("97", str(ctx.exception))
            self.assertIn("security key", str(ctx.exception))

            call.return_value = SimpleNamespace(
                STAT="0",
                PointsRelais=SimpleNamespace(
                    PointRelais_Details=[
                        SimpleNamespace(
                            Num="012345",
                            LgAdr1="PRESSE DU CENTRE ",
                            LgAdr2=None,
                            LgAdr3="1 RUE TEST",
                            LgAdr4="",
                            CP="69001",
                            Ville="LYON      ",
                            Pays="FR",
                            Distance="230",
                        )
                    ]
                ),
            )
            points = carrier._mondialrelay_search_pickup_points(
                "69001", "Lyon", "FR", 1.0
            )
        _, kwargs = call.call_args
        self.assertEqual(kwargs["Enseigne"], "BDTEST13")
        self.assertEqual(kwargs["CP"], "69001")
        self.assertEqual(kwargs["Poids"], "1000")
        self.assertEqual(kwargs["Action"], "24R")
        self.assertEqual(len(kwargs["Security"]), 32)
        self.assertEqual(points[0]["code"], "012345")
        self.assertEqual(points[0]["name"], "PRESSE DU CENTRE")
        self.assertEqual(points[0]["city"], "LYON")
        self.assertEqual(points[0]["distance"], 230.0)

    def test_pickup_wizard_from_sale(self):
        self.relay_carrier.mondialrelay_private_key = False
        order = self._create_order(
            self.relay_carrier, partner_vals={"zip": "69001", "city": "Lyon"}
        )
        wizard = (
            self.env["delivery.mondialrelay.pickup.wizard"]
            .with_context(default_sale_id=order.id)
            .create({"zip": "69001"})
        )
        self.assertEqual(wizard.carrier_id, self.relay_carrier)
        wizard.action_search()
        self.assertTrue(wizard.line_ids)
        wizard.line_ids[0].action_select()
        self.assertEqual(order.mondialrelay_pickup_point_code, "010001")
        self.assertEqual(order.mondialrelay_pickup_point_country, "FR")

    def test_pickup_propagates_to_delivery_on_confirm(self):
        picking = self._create_delivery(self.relay_carrier)
        self.assertEqual(picking.mondialrelay_pickup_point_code, "010001")
        self.assertEqual(picking.mondialrelay_pickup_point_name, "Presse Lyon")
        root = etree.fromstring(self.relay_carrier._mondialrelay_build_request(picking))
        ns = {"r": "http://www.example.org/Request"}
        mode = root.find(".//r:DeliveryMode", ns)
        self.assertEqual(mode.get("Mode"), "24R")
        self.assertEqual(mode.get("Location"), "FR-010001")

    # ------------------------------------------------------------------
    # labels (Connect API)
    # ------------------------------------------------------------------
    def test_request_xml(self):
        picking = self._create_delivery(self.home_carrier)
        root = etree.fromstring(self.home_carrier._mondialrelay_build_request(picking))
        ns = {"r": "http://www.example.org/Request"}
        self.assertEqual(
            root.findtext("r:Context/r:Login", namespaces=ns), "api@example.com"
        )
        self.assertEqual(
            root.findtext("r:Context/r:CustomerId", namespaces=ns), "BDTEST13"
        )
        self.assertEqual(
            root.findtext("r:OutputOptions/r:OutputFormat", namespaces=ns), "10x15"
        )
        self.assertEqual(
            root.findtext("r:OutputOptions/r:OutputType", namespaces=ns), "PdfUrl"
        )
        shipment = root.find(".//r:Shipment", ns)
        self.assertEqual(
            shipment.findtext("r:OrderNo", namespaces=ns),
            picking.sale_id.name.replace("/", "").upper()[:15],
        )
        self.assertEqual(shipment.find("r:DeliveryMode", ns).get("Mode"), "HOM")
        self.assertEqual(shipment.find("r:CollectionMode", ns).get("Mode"), "CCC")
        weight = shipment.find(".//r:Parcel/r:Weight", ns)
        self.assertEqual(weight.get("Value"), "1200")
        self.assertEqual(weight.get("Unit"), "gr")
        recipient = shipment.find("r:Recipient/r:Address", ns)
        self.assertEqual(recipient.findtext("r:Firstname", namespaces=ns), "Marie")
        self.assertEqual(recipient.findtext("r:Lastname", namespaces=ns), "Dupont")
        self.assertEqual(recipient.findtext("r:PostCode", namespaces=ns), "69100")
        self.assertEqual(recipient.findtext("r:CountryCode", namespaces=ns), "FR")
        self.assertEqual(
            recipient.findtext("r:MobileNo", namespaces=ns), "06 12 34 56 78"
        )
        sender = shipment.find("r:Sender/r:Address", ns)
        self.assertEqual(sender.findtext("r:PostCode", namespaces=ns), "75016")

    def test_send_shipping_pdf_mocked(self):
        picking = self._create_delivery(self.relay_carrier)
        responses = [
            FakeResponse(
                (CREATED_XML % (RESPONSE_NS, "https://example.com/label.pdf")).encode()
            ),
        ]
        with patch(CARRIER_MODULE + ".requests.post") as post, patch(
            CARRIER_MODULE + ".requests.get"
        ) as get:
            post.return_value = responses[0]
            get.return_value = FakeResponse(b"%PDF-label")
            result = self.relay_carrier.mondialrelay_send_shipping(picking)
        args, kwargs = post.call_args
        self.assertTrue(args[0].startswith("https://connect-api.mondialrelay.com"))
        self.assertIn(b"<Password>S3cret!</Password>", kwargs["data"])
        get.assert_called_once()
        self.assertEqual(get.call_args[0][0], "https://example.com/label.pdf")
        self.assertEqual(result[0]["tracking_number"], "12345678")
        self.assertEqual(result[0]["exact_price"], 7.99)
        attachment = self.env["ir.attachment"].search(
            [("res_model", "=", "stock.picking"), ("res_id", "=", picking.id)]
        )
        self.assertEqual(len(attachment), 1)
        self.assertTrue(attachment.name.endswith("_12345678.pdf"))

    def test_send_shipping_zpl_and_sandbox(self):
        self.relay_carrier.write(
            {"mondialrelay_label_format": "ZPL", "mondialrelay_sandbox": True}
        )
        picking = self._create_delivery(self.relay_carrier)
        with patch(CARRIER_MODULE + ".requests.post") as post, patch(
            CARRIER_MODULE + ".requests.get"
        ) as get:
            post.return_value = FakeResponse(
                (CREATED_XML % (RESPONSE_NS, "^XA^FDtest^FS^XZ")).encode()
            )
            self.relay_carrier.mondialrelay_send_shipping(picking)
        args, kwargs = post.call_args
        self.assertTrue(args[0].startswith("https://connect-api-sandbox."))
        self.assertIn(b"<OutputType>ZplCode</OutputType>", kwargs["data"])
        get.assert_not_called()
        attachment = self.env["ir.attachment"].search(
            [("res_model", "=", "stock.picking"), ("res_id", "=", picking.id)]
        )
        self.assertTrue(attachment.name.endswith(".zpl"))
        self.assertEqual(attachment.raw, b"^XA^FDtest^FS^XZ")

    def test_send_shipping_surfaces_errors_masked(self):
        picking = self._create_delivery(self.relay_carrier)
        with patch(CARRIER_MODULE + ".requests.post") as post:
            post.return_value = FakeResponse(LOGIN_ERROR_XML.encode())
            with self.assertRaises(UserError) as ctx:
                self.relay_carrier.mondialrelay_send_shipping(picking)
        message = str(ctx.exception)
        self.assertIn("10001", message)
        self.assertIn("mot de passe", message)
        with patch(CARRIER_MODULE + ".requests.post") as post:
            post.side_effect = Exception("boom S3cret! <Password>S3cret!</Password>")
            with self.assertRaises(UserError) as ctx:
                self.relay_carrier.mondialrelay_send_shipping(picking)
        self.assertNotIn("S3cret!", str(ctx.exception))

    def test_send_shipping_requires_api_credentials(self):
        self.relay_carrier.mondialrelay_api_password = False
        picking = self._create_delivery(self.relay_carrier)
        with self.assertRaises(UserError) as ctx:
            self.relay_carrier.mondialrelay_send_shipping(picking)
        self.assertIn("Connect API", str(ctx.exception))

    # ------------------------------------------------------------------
    # fail-closed guards
    # ------------------------------------------------------------------
    def test_check_shipment_rejects_zero_weight(self):
        picking = self._create_delivery(self.relay_carrier, weight=0.0)
        with self.assertRaises(UserError) as ctx:
            self.relay_carrier._mondialrelay_check_shipment(picking)
        self.assertIn("weight", str(ctx.exception))

    def test_check_shipment_rejects_incomplete_address(self):
        picking = self._create_delivery(
            self.relay_carrier, partner_vals={"zip": False, "city": False}
        )
        with self.assertRaises(UserError) as ctx:
            self.relay_carrier._mondialrelay_check_shipment(picking)
        self.assertIn("incomplete", str(ctx.exception))

    def test_check_shipment_requires_pickup_point_and_phone(self):
        picking = self._create_delivery(self.relay_carrier, pickup=False)
        with self.assertRaises(UserError) as ctx:
            self.relay_carrier._mondialrelay_check_shipment(picking)
        self.assertIn("Point Relais", str(ctx.exception))
        picking = self._create_delivery(
            self.home_carrier, partner_vals={"phone": False}
        )
        with self.assertRaises(UserError) as ctx:
            self.home_carrier._mondialrelay_check_shipment(picking)
        self.assertIn("phone", str(ctx.exception))

    def test_payload_falls_back_to_env_company(self):
        self.home_carrier.company_id = False
        picking = self._create_delivery(self.home_carrier)
        root = etree.fromstring(self.home_carrier._mondialrelay_build_request(picking))
        ns = {"r": "http://www.example.org/Request"}
        self.assertEqual(
            root.findtext(".//r:Sender/r:Address/r:City", namespaces=ns), "Paris"
        )

    # ------------------------------------------------------------------
    # tracking, cancellation, secrets, connection test
    # ------------------------------------------------------------------
    def test_tracking_link(self):
        picking = self.env["stock.picking"].new(
            {"carrier_tracking_ref": "12345678, 87654321"}
        )
        link = self.relay_carrier.mondialrelay_get_tracking_link(picking)
        self.assertIn("numeroExpedition=12345678", link)
        self.assertNotIn("87654321", link)

    def test_cancel_shipment_clears_reference(self):
        picking = self._create_delivery(self.relay_carrier)
        picking.carrier_tracking_ref = "12345678"
        self.relay_carrier.mondialrelay_cancel_shipment(picking)
        self.assertFalse(picking.carrier_tracking_ref)

    def test_mask_secrets(self):
        masked = self.relay_carrier._mondialrelay_mask_secrets(
            "pw=S3cret! key=TestAPI1key <Password>S3cret!</Password>"
        )
        self.assertNotIn("S3cret!", masked)
        self.assertNotIn("TestAPI1key", masked)
        self.assertIn("<Password>****</Password>", masked)

    def test_test_connection(self):
        self.relay_carrier.mondialrelay_private_key = False
        with self.assertRaises(UserError):
            self.relay_carrier.action_mondialrelay_test_connection()
        self.relay_carrier.mondialrelay_private_key = "TestAPI1key"
        with patch(CARRIER_MODULE + ".ZeepClient") as zeep_client, patch(
            CARRIER_MODULE + ".requests.post"
        ) as post:
            call = zeep_client.return_value.service.WSI4_PointRelais_Recherche
            call.return_value = SimpleNamespace(
                STAT="0", PointsRelais=SimpleNamespace(PointRelais_Details=[])
            )
            post.return_value = FakeResponse(LOGIN_ERROR_XML.encode())
            with self.assertRaises(UserError) as ctx:
                self.relay_carrier.action_mondialrelay_test_connection()
            self.assertIn("10001", str(ctx.exception))
            post.return_value = FakeResponse(EMPTY_XML.encode())
            action = self.relay_carrier.action_mondialrelay_test_connection()
        self.assertIn("Connection successful", action["params"]["message"])

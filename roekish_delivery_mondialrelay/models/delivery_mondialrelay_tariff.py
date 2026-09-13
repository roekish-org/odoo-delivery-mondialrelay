# Copyright 2026 ROEKISH
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models

# Mondial Relay pricing zones: France, then the European countries served by
# Mondial Relay, grouped the way its public grids price them.
MONDIALRELAY_ZONES = [
    ("FR", "France (metropolitan, Monaco)"),
    ("EU1", "Europe zone 1 (Belgium, Luxembourg, Netherlands, Germany)"),
    ("EU2", "Europe zone 2 (Spain, United Kingdom)"),
    ("EU3", "Europe zone 3 (Italy, Portugal, Austria)"),
]


class DeliveryMondialrelayTariff(models.Model):
    _name = "delivery.mondialrelay.tariff"
    _description = "Mondial Relay Tariff Grid Line"
    _order = "carrier_id, zone, max_weight"

    carrier_id = fields.Many2one(
        "delivery.carrier",
        string="Carrier",
        required=True,
        ondelete="cascade",
        index=True,
    )
    zone = fields.Selection(
        selection=MONDIALRELAY_ZONES,
        string="Zone",
        required=True,
    )
    max_weight = fields.Float(
        string="Weight up to (kg)",
        required=True,
        help="This line applies to shipments whose total weight is at or "
        "below this value, for the selected zone.",
    )
    price = fields.Float(
        string="Price",
        required=True,
        help="Delivery price charged to the customer, expressed in the "
        "carrier company currency.",
    )
    currency_id = fields.Many2one(
        related="carrier_id.company_id.currency_id",
        readonly=True,
    )
    delay_min = fields.Integer(
        string="Delivery days min",
        help="Shortest delivery time announced for this zone, in working days "
        "after hand-over. Leave 0 to use the carrier delivery time.",
    )
    delay_max = fields.Integer(
        string="Delivery days max",
        help="Longest delivery time announced for this zone, in working days "
        "after hand-over. Leave 0 to use the carrier delivery time.",
    )

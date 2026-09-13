# Copyright 2026 ROEKISH
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models


class MondialrelayPickupMixin(models.AbstractModel):
    """Point Relais holder shared by sale.order and stock.picking."""

    _name = "delivery.mondialrelay.pickup.mixin"
    _description = "Mondial Relay Point Relais holder"

    mondialrelay_pickup_point_code = fields.Char(string="Point Relais ID", copy=False)
    mondialrelay_pickup_point_name = fields.Char(string="Point Relais", copy=False)
    mondialrelay_pickup_point_street = fields.Char(
        string="Point Relais street", copy=False
    )
    mondialrelay_pickup_point_zip = fields.Char(string="Point Relais ZIP", copy=False)
    mondialrelay_pickup_point_city = fields.Char(string="Point Relais city", copy=False)
    mondialrelay_pickup_point_country = fields.Char(
        string="Point Relais country",
        copy=False,
        help="ISO country code of the Point Relais, sent with its ID on the label.",
    )
    mondialrelay_is_pickup = fields.Boolean(
        string="Mondial Relay pickup delivery",
        compute="_compute_mondialrelay_is_pickup",
        help="The selected carrier delivers to a Point Relais or a Locker.",
    )

    @api.depends("carrier_id")
    def _compute_mondialrelay_is_pickup(self):
        for rec in self:
            carrier = rec.carrier_id
            rec.mondialrelay_is_pickup = (
                carrier.delivery_type == "mondialrelay"
                and carrier.mondialrelay_delivery_mode in ("24R", "24L")
            )

    def action_mondialrelay_choose_pickup_point(self):
        self.ensure_one()
        default_key = (
            "default_picking_id" if self._name == "stock.picking" else "default_sale_id"
        )
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Choose a Point Relais"),
            "res_model": "delivery.mondialrelay.pickup.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {default_key: self.id},
        }

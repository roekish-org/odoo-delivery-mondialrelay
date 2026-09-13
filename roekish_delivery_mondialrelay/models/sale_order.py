# Copyright 2026 ROEKISH
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import models

PICKUP_FIELDS = (
    "mondialrelay_pickup_point_code",
    "mondialrelay_pickup_point_name",
    "mondialrelay_pickup_point_street",
    "mondialrelay_pickup_point_zip",
    "mondialrelay_pickup_point_city",
    "mondialrelay_pickup_point_country",
)


class SaleOrder(models.Model):
    _name = "sale.order"
    _inherit = ["sale.order", "delivery.mondialrelay.pickup.mixin"]

    def _action_confirm(self):
        res = super()._action_confirm()
        # Carry the chosen Point Relais onto the delivery orders created at
        # confirmation, unless one was already set on the picking.
        for order in self:
            if not order.mondialrelay_pickup_point_code:
                continue
            pickings = order.picking_ids.filtered(
                lambda p: p.mondialrelay_is_pickup
                and not p.mondialrelay_pickup_point_code
            )
            pickings.write({name: order[name] for name in PICKUP_FIELDS})
        return res

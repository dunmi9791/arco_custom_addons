from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _name = "sale.order"
    _inherit = ["sale.order", "tier.validation"]
    _state_from = ["draft", "sent"]
    _state_to = ["sale"]
    _cancel_state = "cancel"
    _tier_validation_manual_config = False

    arco_max_discount = fields.Float(
        "Highest Discount %", compute="_compute_arco_discount", store=True, digits=(16, 2)
    )
    arco_discount_band = fields.Selection(
        [("exec", "0-5% (Sales Executive)"), ("manager", "5-15% (Sales Manager)"), ("director", "Above 15% (Commercial Director)")],
        string="Discount Approval Band", compute="_compute_arco_discount", store=True,
    )
    arco_stock_warning = fields.Text("Availability", compute="_compute_arco_stock_warning")

    @api.depends("order_line.discount", "order_line.display_type")
    def _compute_arco_discount(self):
        for order in self:
            disc = max(order.order_line.filtered(lambda l: not l.display_type).mapped("discount") or [0.0])
            order.arco_max_discount = disc
            order.arco_discount_band = "exec" if disc <= 5 else ("manager" if disc <= 15 else "director")

    def _arco_stock_shortages(self):
        """[(line, needed, free)] for storable products short in the order's warehouse."""
        self.ensure_one()
        shortages = []
        needed = {}
        for line in self.order_line.filtered(lambda l: l.product_id.is_storable and not l.display_type):
            qty = line.product_uom._compute_quantity(line.product_uom_qty, line.product_id.uom_id)
            needed[line.product_id] = needed.get(line.product_id, 0.0) + qty
        for product, qty in needed.items():
            free = product.with_context(warehouse_id=self.warehouse_id.id).free_qty
            if qty > free:
                shortages.append((product, qty, free))
        return shortages

    @api.depends("order_line.product_id", "order_line.product_uom_qty", "warehouse_id")
    def _compute_arco_stock_warning(self):
        for order in self:
            shortages = order._arco_stock_shortages() if order.state in ("draft", "sent") else []
            order.arco_stock_warning = "\n".join(
                _("%(p)s: ordered %(q)s, available %(f)s", p=p.display_name, q=q, f=f) for p, q, f in shortages
            ) or False

    def action_confirm(self):
        for order in self.filtered(lambda o: o.state in ("draft", "sent")):
            policy = order.company_id.arco_sale_stock_policy
            shortages = order._arco_stock_shortages() if policy != "none" else []
            if shortages:
                msg = "\n".join(
                    _("%(p)s: ordered %(q)s, available %(f)s", p=p.display_name, q=q, f=f) for p, q, f in shortages
                )
                if policy == "block":
                    raise UserError(_("Insufficient stock to confirm %(o)s:\n%(m)s", o=order.name, m=msg))
                order.message_post(body=_("Confirmed with stock shortage:\n%s", msg))
        res = super().action_confirm()
        self._arco_auto_invoice()
        return res

    def _arco_auto_invoice(self):
        for order in self.filtered(lambda o: o.state == "sale" and o.company_id.arco_sale_auto_invoice):
            if not any(l.qty_to_invoice > 0 for l in order.order_line):
                continue  # delivered-quantity policy: invoiced after delivery
            invoices = order._create_invoices()
            if order.company_id.arco_sale_auto_post:
                invoices.action_post()
            order.message_post(body=_("Invoice %s generated automatically on confirmation.",
                                      ", ".join(invoices.mapped("display_name"))))


class ResCompany(models.Model):
    _inherit = "res.company"

    arco_sale_stock_policy = fields.Selection(
        [("none", "No check"), ("warn", "Warn"), ("block", "Block")], default="warn",
        string="Stock check on SO confirmation",
    )
    arco_sale_auto_invoice = fields.Boolean("Create invoice on SO confirmation", default=True)
    arco_sale_auto_post = fields.Boolean("Post the automatic invoice", default=False)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    arco_sale_stock_policy = fields.Selection(related="company_id.arco_sale_stock_policy", readonly=False)
    arco_sale_auto_invoice = fields.Boolean(related="company_id.arco_sale_auto_invoice", readonly=False)
    arco_sale_auto_post = fields.Boolean(related="company_id.arco_sale_auto_post", readonly=False)


class TierDefinition(models.Model):
    _inherit = "tier.definition"

    @api.model
    def _get_tier_validation_model_names(self):
        res = super()._get_tier_validation_model_names()
        res.append("sale.order")
        return res

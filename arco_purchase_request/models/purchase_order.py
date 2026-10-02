from odoo import api, fields, models
from odoo.tools import float_compare


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    arco_request_line_id = fields.Many2one(
        "arco.purchase.request.line", string="Requisition Line", copy=False, index=True, readonly=True
    )


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    arco_request_ids = fields.Many2many(
        "arco.purchase.request", compute="_compute_arco_request_ids", string="Requisitions"
    )
    arco_request_count = fields.Integer(compute="_compute_arco_request_ids")

    @api.depends("order_line.arco_request_line_id")
    def _compute_arco_request_ids(self):
        for po in self:
            reqs = po.order_line.mapped("arco_request_line_id.request_id")
            po.arco_request_ids = reqs
            po.arco_request_count = len(reqs)

    @api.depends(
        "amount_total_cc",
        "order_line.arco_request_line_id",
        "order_line.arco_request_line_id.request_id.state",
        "company_id.arco_pr_po_tolerance",
    )
    def _compute_arco_pr_preapproved(self):
        """A PO is pre-approved when every product line comes from an approved requisition
        and its untaxed company-currency value stays within the PR estimate + tolerance."""
        super()._compute_arco_pr_preapproved()
        for po in self:
            lines = po.order_line.filtered(lambda l: not l.display_type)
            pr_lines = lines.mapped("arco_request_line_id")
            if not lines or any(not l.arco_request_line_id for l in lines):
                continue
            if any(r.state not in ("approved", "done") for r in pr_lines.request_id):
                continue
            estimate = sum(pr_lines.mapped("subtotal"))
            limit = estimate * (1 + (po.company_id.arco_pr_po_tolerance or 0.0) / 100.0)
            untaxed_cc = po.currency_id._convert(
                po.amount_untaxed, po.company_id.currency_id, po.company_id,
                po.date_order or fields.Date.today(),
            )
            po.arco_pr_preapproved = (
                float_compare(untaxed_cc, limit, precision_rounding=po.company_id.currency_id.rounding) <= 0
            )

    def action_view_arco_requests(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Requisitions",
            "res_model": "arco.purchase.request",
            "view_mode": "list,form",
            "domain": [("id", "in", self.arco_request_ids.ids)],
        }


class ResCompany(models.Model):
    _inherit = "res.company"

    arco_pr_po_tolerance = fields.Float(
        "PR to PO Tolerance (%)",
        default=10.0,
        help="A PO raised from an approved requisition skips the authorization matrix unless its "
        "untaxed value exceeds the requisition estimate by more than this percentage.",
    )

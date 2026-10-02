from odoo import api, fields, models


class PurchaseOrder(models.Model):
    _name = "purchase.order"
    _inherit = ["purchase.order", "tier.validation"]
    _state_from = ["draft", "sent", "to approve"]
    _state_to = ["purchase", "done"]
    _tier_validation_manual_config = False

    arco_pr_preapproved = fields.Boolean(
        "Covered by Approved Requisition",
        compute="_compute_arco_pr_preapproved",
        store=True,
        help="Every line comes from an approved Purchase Requisition and the PO total is within "
        "the requisition estimate plus tolerance, so the authorization matrix is not applied twice.",
    )

    @api.depends("amount_total_cc")
    def _compute_arco_pr_preapproved(self):
        # arco_purchase_request extends this with the PR link check
        for order in self:
            order.arco_pr_preapproved = False

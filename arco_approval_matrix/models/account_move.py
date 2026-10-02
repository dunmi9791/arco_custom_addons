from odoo import api, fields, models


class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "tier.validation"]
    _state_from = ["draft"]
    _state_to = ["posted"]
    _tier_validation_manual_config = False

    arco_amount_company = fields.Monetary(
        "Total (Company Currency)",
        currency_field="company_currency_id",
        compute="_compute_arco_amount_company",
        store=True,
    )

    @api.depends("amount_total_signed")
    def _compute_arco_amount_company(self):
        for move in self:
            move.arco_amount_company = abs(move.amount_total_signed)

    def _get_under_validation_exceptions(self):
        # allow the usual draft edits on bills while under review
        res = super()._get_under_validation_exceptions()
        return res + ["needed_terms_dirty", "invoice_line_ids", "line_ids"]

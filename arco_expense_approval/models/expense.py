from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrExpense(models.Model):
    _inherit = "hr.expense"

    arco_no_receipt_reason = fields.Char(
        "No Receipt Reason",
        help="Only when a receipt cannot be obtained (e.g. per-diem, local transport). "
        "Finance sees this during verification.",
    )


class HrExpenseSheet(models.Model):
    _name = "hr.expense.sheet"
    _inherit = ["hr.expense.sheet", "tier.validation"]
    _state_field = "approval_state"
    _state_from = ["submit"]
    _state_to = ["approve"]
    _cancel_state = "cancel"
    _tier_validation_manual_config = False

    arco_budget_status = fields.Html("Budget Check", compute="_compute_arco_budget_status")
    arco_missing_receipts = fields.Integer("Lines without receipt", compute="_compute_arco_missing_receipts")

    @api.depends("expense_line_ids.attachment_ids", "expense_line_ids.arco_no_receipt_reason")
    def _compute_arco_missing_receipts(self):
        for sheet in self:
            sheet.arco_missing_receipts = len(sheet.expense_line_ids.filtered(
                lambda e: not e.attachment_ids and not e.arco_no_receipt_reason
            ))

    def _arco_budget_requests(self):
        self.ensure_one()
        return [{
            "distribution": exp.analytic_distribution,
            "account": exp.account_id,
            "amount": exp.total_amount,
            "date": exp.date or fields.Date.today(),
            "company": exp.company_id,
        } for exp in self.expense_line_ids if exp.analytic_distribution]

    def _compute_arco_budget_status(self):
        BudgetLine = self.env["arco.budget.line"]
        for sheet in self:
            rows = []
            for req in sheet._arco_budget_requests():
                for key, pct in req["distribution"].items():
                    for aid in str(key).split(","):
                        line = BudgetLine.sudo()._arco_find_line(req["company"], int(aid), req["account"], req["date"])
                        if not line:
                            continue
                        need = req["amount"] * pct / 100.0
                        ok = line.currency_id.compare_amounts(need, line.available_amount) <= 0
                        rows.append(
                            f"<li class='{'text-success' if ok else 'text-danger'}'>{line.display_name}: "
                            f"claim {need:,.2f} / available {line.available_amount:,.2f}</li>"
                        )
            sheet.arco_budget_status = (
                "<ul>%s</ul>" % "".join(rows) if rows else _("<p class='text-muted'>No budget line found for this claim's cost centres.</p>")
            )

    # ------------------------------------------------------------------ flow
    def action_submit_sheet(self):
        for sheet in self:
            missing = sheet.expense_line_ids.filtered(lambda e: not e.attachment_ids and not e.arco_no_receipt_reason)
            if missing:
                raise UserError(_(
                    "Attach a receipt to every expense before submitting (or give a reason):\n- %s",
                    "\n- ".join(missing.mapped("name")),
                ))
            self.env["arco.budget.line"]._arco_check_budget(sheet._arco_budget_requests(), sheet)
        res = super().action_submit_sheet()
        for sheet in self.filtered(lambda s: s.approval_state == "submit"):
            sheet.request_validation()
        return res

    def _validate_tier(self, tiers=False):
        res = super()._validate_tier(tiers)
        for sheet in self.filtered(lambda s: s.approval_state == "submit" and s.validated):
            # all tiers passed: approve (creates the draft entry) regardless of expense-manager rights
            sheet.sudo().with_context(skip_validation_check=True)._do_approve()
            sheet.message_post(body=_("Expense report approved by Line Manager and Finance. Ready for posting and payment."))
        return res

    def _rejected_tier(self, tiers=False):
        res = super()._rejected_tier(tiers)
        for sheet in self.filtered(lambda s: s.approval_state == "submit"):
            sheet.sudo().with_context(skip_validation_check=True)._do_refuse(_("Rejected during approval by %s", self.env.user.name))
        return res

    def action_reset_expense_sheets(self):
        self.restart_validation()
        return super().action_reset_expense_sheets()


class TierDefinition(models.Model):
    _inherit = "tier.definition"

    @api.model
    def _get_tier_validation_model_names(self):
        res = super()._get_tier_validation_model_names()
        res.append("hr.expense.sheet")
        return res

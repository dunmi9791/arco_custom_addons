from odoo import _, fields, models
from odoo.exceptions import UserError


class ArcoApprovalCategory(models.Model):
    _inherit = "arco.approval.category"

    request_type = fields.Selection(
        selection_add=[("budget_transfer", "Budget transfer")], ondelete={"budget_transfer": "set default"}
    )


class ArcoApprovalRequest(models.Model):
    _inherit = "arco.approval.request"

    budget_from_line_id = fields.Many2one(
        "arco.budget.line", string="Transfer From", domain="[('budget_state', '=', 'approved')]"
    )
    budget_to_line_id = fields.Many2one(
        "arco.budget.line", string="Transfer To", domain="[('budget_state', '=', 'approved')]"
    )
    budget_from_available = fields.Monetary(
        related="budget_from_line_id.available_amount", string="Available in Source",
        currency_field="company_currency_id",
    )

    def _check_submit(self):
        res = super()._check_submit()
        for rec in self.filtered(lambda r: r.request_type == "budget_transfer"):
            rec._arco_check_transfer()
        return res

    def _arco_check_transfer(self):
        self.ensure_one()
        if not (self.budget_from_line_id and self.budget_to_line_id):
            raise UserError(_("Select the source and destination budget lines."))
        if self.budget_from_line_id == self.budget_to_line_id:
            raise UserError(_("Source and destination must differ."))
        if self.amount_company <= 0:
            raise UserError(_("Enter the amount to transfer."))
        if self.company_currency_id.compare_amounts(self.amount_company, self.budget_from_line_id.available_amount) > 0:
            raise UserError(_("Only %s is available on the source budget line.", self.budget_from_line_id.available_amount))

    def _execute_budget_transfer(self):
        self._arco_check_transfer()
        self.message_post(body=_(
            "Budget transfer executed: %(amount)s from %(src)s to %(dst)s",
            amount=self.amount_company, src=self.budget_from_line_id.display_name,
            dst=self.budget_to_line_id.display_name,
        ))


class ArcoBudgetLine(models.Model):
    _inherit = "arco.budget.line"

    def _compute_transfer_amount(self):
        done = self.env["arco.approval.request"].search([
            ("request_type", "=", "budget_transfer"),
            ("state", "=", "done"),
            "|", ("budget_from_line_id", "in", self.ids), ("budget_to_line_id", "in", self.ids),
        ])
        for line in self:
            incoming = sum(done.filtered(lambda r: r.budget_to_line_id == line).mapped("amount_company"))
            outgoing = sum(done.filtered(lambda r: r.budget_from_line_id == line).mapped("amount_company"))
            line.transfer_amount = incoming - outgoing

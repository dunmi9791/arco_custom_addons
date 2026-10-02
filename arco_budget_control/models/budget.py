from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


def distribution_share(distribution, analytic_id):
    """Percentage of an analytic distribution that hits `analytic_id`.
    Keys can combine several plans ("12,40"), so each key is split."""
    pct = 0.0
    for key, value in (distribution or {}).items():
        if str(analytic_id) in str(key).split(","):
            pct += value
    return pct / 100.0


class ArcoBudgetItem(models.Model):
    _name = "arco.budget.item"
    _description = "Budget Item"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    account_ids = fields.Many2many(
        "account.account", string="GL Accounts",
        help="Postings on these accounts consume this budget item.",
    )


class ArcoBudget(models.Model):
    _name = "arco.budget"
    _description = "Budget"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_from desc, id desc"

    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    control_policy = fields.Selection(
        [("none", "Monitor only"), ("warn", "Warn"), ("block", "Block")],
        default="warn", required=True, tracking=True,
        help="What happens when a requisition or PO exceeds the available budget.",
    )
    state = fields.Selection(
        [("draft", "Draft"), ("approved", "Approved"), ("closed", "Closed")], default="draft", tracking=True
    )
    approved_by = fields.Many2one("res.users", readonly=True, copy=False)
    line_ids = fields.One2many("arco.budget.line", "budget_id", copy=True)
    planned_total = fields.Monetary(compute="_compute_totals", string="Budget")
    actual_total = fields.Monetary(compute="_compute_totals", string="Actual")
    committed_total = fields.Monetary(compute="_compute_totals", string="Committed")
    available_total = fields.Monetary(compute="_compute_totals", string="Available")

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for rec in self:
            if rec.date_from > rec.date_to:
                raise ValidationError(_("The budget end date must be after the start date."))

    def _compute_totals(self):
        for rec in self:
            lines = rec.line_ids
            rec.planned_total = sum(lines.mapped("planned_amount"))
            rec.actual_total = sum(lines.mapped("actual_amount"))
            rec.committed_total = sum(lines.mapped("committed_amount"))
            rec.available_total = sum(lines.mapped("available_amount"))

    def action_approve(self):
        if not self.env.user.has_group("arco_base.group_arco_finance_director"):
            raise UserError(_("Only the Finance Director can approve budgets."))
        self.write({"state": "approved", "approved_by": self.env.user.id})

    def action_close(self):
        self.write({"state": "closed"})

    def action_draft(self):
        self.write({"state": "draft", "approved_by": False})

    def action_open_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Budget vs Actual - %s", self.name),
            "res_model": "arco.budget.line",
            "view_mode": "list",
            "domain": [("budget_id", "=", self.id)],
            "context": {"search_default_group_analytic": 1},
        }


class ArcoBudgetLine(models.Model):
    _name = "arco.budget.line"
    _description = "Budget Line"
    _order = "budget_id, analytic_account_id, item_id"
    _rec_names_search = ["analytic_account_id", "item_id"]

    budget_id = fields.Many2one("arco.budget", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="budget_id.company_id", store=True)
    currency_id = fields.Many2one(related="budget_id.currency_id")
    budget_state = fields.Selection(related="budget_id.state", store=True)
    date_from = fields.Date(related="budget_id.date_from", store=True)
    date_to = fields.Date(related="budget_id.date_to", store=True)
    analytic_account_id = fields.Many2one(
        "account.analytic.account", string="Cost Centre / Project", required=True, index=True
    )
    analytic_plan_id = fields.Many2one(related="analytic_account_id.plan_id", store=True, string="Plan")
    item_id = fields.Many2one("arco.budget.item", string="Budget Item", required=True)
    original_amount = fields.Monetary("Original Budget")
    transfer_amount = fields.Monetary("Transfers", compute="_compute_transfer_amount")
    planned_amount = fields.Monetary("Revised Budget", compute="_compute_amounts")
    actual_amount = fields.Monetary("Actual", compute="_compute_amounts")
    committed_amount = fields.Monetary("Committed", compute="_compute_amounts")
    available_amount = fields.Monetary("Available", compute="_compute_amounts")
    variance_amount = fields.Monetary("Variance (Budget - Actual)", compute="_compute_amounts")
    utilisation_pct = fields.Float("Used %", compute="_compute_amounts", digits=(16, 1))

    _sql_constraints = [
        ("line_unique", "unique(budget_id, analytic_account_id, item_id)",
         "Only one line per cost centre and budget item on a budget."),
    ]

    @api.depends("analytic_account_id", "item_id")
    def _compute_display_name(self):
        for line in self:
            line.display_name = f"{line.budget_id.name} / {line.analytic_account_id.name} / {line.item_id.name}"

    def _compute_transfer_amount(self):
        # extended in approval.py (budget transfers)
        for line in self:
            line.transfer_amount = 0.0

    def _compute_amounts(self):
        for line in self:
            actual = line._arco_actual()
            committed = line._arco_committed()
            planned = line.original_amount + line.transfer_amount
            line.planned_amount = planned
            line.actual_amount = actual
            line.committed_amount = committed
            line.available_amount = planned - actual - committed
            line.variance_amount = planned - actual
            line.utilisation_pct = (actual + committed) / planned * 100 if planned else 0.0

    # ------------------------------------------------------------ measures
    def _arco_actual(self):
        self.ensure_one()
        if not self.item_id.account_ids:
            return 0.0
        amls = self.env["account.move.line"].sudo().search([
            ("company_id", "child_of", self.company_id.id),
            ("parent_state", "=", "posted"),
            ("account_id", "in", self.item_id.account_ids.ids),
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
            ("analytic_distribution", "in", [self.analytic_account_id.id]),
        ])
        return sum(aml.balance * distribution_share(aml.analytic_distribution, self.analytic_account_id.id)
                   for aml in amls)

    def _arco_committed(self, exclude=None):
        """Open purchase commitments: confirmed PO lines not yet billed, plus requisitions
        submitted/approved but not yet converted to POs."""
        self.ensure_one()
        exclude = exclude or {}
        aid = self.analytic_account_id.id
        accounts = self.item_id.account_ids
        total = 0.0
        pols = self.env["purchase.order.line"].sudo().search([
            ("company_id", "child_of", self.company_id.id),
            ("state", "in", ("purchase", "done")),
            ("display_type", "=", False),
            ("analytic_distribution", "in", [aid]),
            ("date_planned", ">=", self.date_from),
            ("date_planned", "<=", fields.Datetime.to_datetime(self.date_to).replace(hour=23, minute=59)),
        ])
        for pol in pols - exclude.get("purchase.order.line", self.env["purchase.order.line"]):
            if pol._arco_budget_account() not in accounts:
                continue
            open_qty = max(pol.product_qty - pol.qty_invoiced, 0.0)
            if not pol.product_qty:
                continue
            amount = pol.price_subtotal * open_qty / pol.product_qty
            amount = pol.currency_id._convert(amount, self.currency_id, self.company_id, pol.date_order or fields.Date.today())
            total += amount * distribution_share(pol.analytic_distribution, aid)
        prls = self.env["arco.purchase.request.line"].sudo().search([
            ("company_id", "child_of", self.company_id.id),
            ("state", "in", ("submitted", "approved")),
            ("analytic_distribution", "in", [aid]),
        ])
        for prl in prls - exclude.get("arco.purchase.request.line", self.env["arco.purchase.request.line"]):
            req_date = prl.request_id.date_required or prl.request_id.date_request
            if not (self.date_from <= req_date <= self.date_to):
                continue
            if prl.purchase_line_ids or prl._arco_budget_account() not in accounts:
                continue
            total += prl.subtotal * distribution_share(prl.analytic_distribution, aid)
        return total

    # ------------------------------------------------------------ check API
    @api.model
    def _arco_find_line(self, company, analytic_id, account, date):
        return self.search([
            ("company_id", "in", company.parent_ids.ids),
            ("budget_state", "=", "approved"),
            ("analytic_account_id", "=", analytic_id),
            ("item_id.account_ids", "in", account.id),
            ("date_from", "<=", date),
            ("date_to", ">=", date),
        ], limit=1)

    @api.model
    def _arco_check_budget(self, requests, record):
        """requests: iterable of dict(distribution, account, amount, date, company).
        Returns a list of messages for budget lines that would be overspent; raises when a
        budget with the 'block' policy is exceeded; posts a warning on `record` for 'warn'."""
        need = defaultdict(float)
        for req in requests:
            if not req["account"] or not req["distribution"]:
                continue
            for key, pct in req["distribution"].items():
                for aid in str(key).split(","):
                    line = self._arco_find_line(req["company"], int(aid), req["account"], req["date"])
                    if line:
                        need[line] += req["amount"] * pct / 100.0
        problems, blocking = [], False
        for line, amount in need.items():
            if line.currency_id.compare_amounts(amount, line.available_amount) > 0:
                msg = _(
                    "%(line)s: needs %(need)s, available %(avail)s",
                    line=line.display_name,
                    need=f"{line.currency_id.symbol}{amount:,.2f}",
                    avail=f"{line.currency_id.symbol}{line.available_amount:,.2f}",
                )
                problems.append(msg)
                if line.budget_id.control_policy == "block":
                    blocking = True
                if line.budget_id.control_policy in ("warn", "block") and record:
                    record.message_post(body=_("Budget exceeded - %s", msg))
        if blocking:
            raise UserError(_("Budget not available:\n%s", "\n".join(problems)))
        return problems

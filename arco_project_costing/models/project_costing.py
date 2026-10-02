from odoo import api, fields, models


class ArcoCostCategory(models.Model):
    _name = "arco.cost.category"
    _description = "Project Cost Category"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    account_ids = fields.Many2many(
        "account.account", string="GL Accounts",
        help="Analytic items posted to these accounts count as actual cost of this category",
    )


class ArcoProjectBudgetLine(models.Model):
    _name = "arco.project.budget.line"
    _description = "Project Budget Line"
    _order = "project_id, sequence, id"

    project_id = fields.Many2one("project.project", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    category_id = fields.Many2one("arco.cost.category", required=True)
    name = fields.Char("Description")
    currency_id = fields.Many2one(related="project_id.arco_currency_id")
    planned_amount = fields.Monetary("Budget")
    committed_amount = fields.Monetary("Committed (open POs)", compute="_compute_amounts")
    actual_amount = fields.Monetary("Actual", compute="_compute_amounts")
    remaining_amount = fields.Monetary("Remaining", compute="_compute_amounts")
    consumed_pct = fields.Float("Consumed %", compute="_compute_amounts")

    def _compute_amounts(self):
        for line in self:
            proj = line.project_id
            actual = committed = 0.0
            if proj.account_id:
                accounts = line.category_id.account_ids
                if accounts:
                    items = self.env["account.analytic.line"].search([
                        ("account_id", "=", proj.account_id.id),
                        ("general_account_id", "in", accounts.ids),
                    ])
                    actual = -sum(items.mapped("amount"))
                committed = sum(
                    proj._arco_open_po_lines().filtered(
                        lambda l: l._arco_cost_category() == line.category_id
                    ).mapped(lambda l: proj._arco_po_line_open_amount(l))
                )
            line.actual_amount = actual
            line.committed_amount = committed
            line.remaining_amount = line.planned_amount - actual - committed
            line.consumed_pct = (actual + committed) / line.planned_amount * 100 if line.planned_amount else 0.0


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    def _arco_cost_category(self):
        self.ensure_one()
        account = self.product_id.product_tmpl_id.get_product_accounts(
            fiscal_pos=self.order_id.fiscal_position_id
        ).get("expense")
        if not account:
            return self.env["arco.cost.category"]
        return self.env["arco.cost.category"].search([("account_ids", "in", account.id)], limit=1)


class ProjectProject(models.Model):
    _inherit = "project.project"

    arco_currency_id = fields.Many2one("res.currency", compute="_compute_arco_currency_id")
    arco_contract_value = fields.Monetary("Contract Value", currency_field="arco_currency_id")
    arco_budget_line_ids = fields.One2many("arco.project.budget.line", "project_id", string="Budget")
    arco_budget_total = fields.Monetary(currency_field="arco_currency_id", string="Total Budget", compute="_compute_arco_costing")
    arco_actual_cost = fields.Monetary(currency_field="arco_currency_id", string="Actual Cost", compute="_compute_arco_costing")
    arco_committed_cost = fields.Monetary(currency_field="arco_currency_id", string="Committed Cost", compute="_compute_arco_costing")
    arco_revenue = fields.Monetary(currency_field="arco_currency_id", string="Revenue Invoiced", compute="_compute_arco_costing")
    arco_margin = fields.Monetary(currency_field="arco_currency_id", string="Margin (to date)", compute="_compute_arco_costing")
    arco_margin_pct = fields.Float("Margin %", compute="_compute_arco_costing")
    arco_budget_consumed_pct = fields.Float("Budget Consumed %", compute="_compute_arco_costing")

    def _compute_arco_currency_id(self):
        for proj in self:
            proj.arco_currency_id = (proj.company_id or self.env.company).currency_id

    def _arco_open_po_lines(self):
        self.ensure_one()
        if not self.account_id:
            return self.env["purchase.order.line"]
        lines = self.env["purchase.order.line"].search([
            ("order_id.state", "in", ("purchase", "done")),
            ("analytic_distribution", "!=", False),
        ])
        key = str(self.account_id.id)
        return lines.filtered(
            lambda l: any(key in k.split(",") for k in (l.analytic_distribution or {}))
            and l.qty_invoiced < l.product_qty
        )

    def _arco_po_line_open_amount(self, line):
        pct = 0.0
        for k, v in (line.analytic_distribution or {}).items():
            if str(self.account_id.id) in k.split(","):
                pct += v
        open_qty = line.product_qty - line.qty_invoiced
        amount = open_qty * line.price_unit * pct / 100.0
        return line.currency_id._convert(amount, self.arco_currency_id, self.company_id or self.env.company, fields.Date.today())

    def _compute_arco_costing(self):
        AAL = self.env["account.analytic.line"]
        for proj in self:
            revenue = cost = committed = 0.0
            if proj.account_id:
                items = AAL.search([("account_id", "=", proj.account_id.id)])
                revenue = sum(a for a in items.mapped("amount") if a > 0)
                cost = -sum(a for a in items.mapped("amount") if a < 0)
                committed = sum(proj._arco_po_line_open_amount(l) for l in proj._arco_open_po_lines())
            budget = sum(proj.arco_budget_line_ids.mapped("planned_amount"))
            proj.arco_budget_total = budget
            proj.arco_actual_cost = cost
            proj.arco_committed_cost = committed
            proj.arco_revenue = revenue
            proj.arco_margin = revenue - cost
            proj.arco_margin_pct = (revenue - cost) / revenue * 100 if revenue else 0.0
            proj.arco_budget_consumed_pct = (cost + committed) / budget * 100 if budget else 0.0

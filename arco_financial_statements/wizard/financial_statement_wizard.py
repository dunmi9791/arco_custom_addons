from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ArcoFinancialStatementWizard(models.TransientModel):
    _name = "arco.financial.statement.wizard"
    _description = "Financial Statements"

    statement = fields.Selection(
        [("pl", "Profit & Loss"), ("bs", "Balance Sheet"), ("cf", "Cash Flow Statement"), ("all", "All three")],
        required=True, default="pl",
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company.root_id, required=True)
    branch_ids = fields.Many2many(
        "res.company", string="Branches",
        domain="[('id', 'child_of', company_id)]",
        help="Leave empty for the whole company including all branches (AMEL, AMOS, AISL, AWS).",
    )
    date_from = fields.Date(required=True, default=lambda self: fields.Date.context_today(self).replace(month=1, day=1))
    date_to = fields.Date(required=True, default=fields.Date.context_today)
    comparison = fields.Selection(
        [("none", "No comparative"), ("prior_period", "Previous period"), ("prior_year", "Same period last year")],
        default="prior_year", required=True,
    )
    posted_only = fields.Boolean("Posted entries only", default=True)
    show_accounts = fields.Boolean("Show account detail", default=True)

    def _companies(self):
        self.ensure_one()
        if self.branch_ids:
            return self.env["res.company"].search([("id", "child_of", self.branch_ids.ids)])
        return self.env["res.company"].search([("id", "child_of", self.company_id.id)])

    def _report_data(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("The start date must be before the end date."))
        engine = self.env["arco.financial.statement"]
        companies = self._companies()
        cmp_from, cmp_to = engine.comparative_period(self.date_from, self.date_to, self.comparison)
        stmts = ["pl", "bs", "cf"] if self.statement == "all" else [self.statement]
        data = {
            "statements": stmts,
            "company_name": self.company_id.name,
            "branches": ", ".join(self.branch_ids.mapped("name")),
            "currency_id": self.company_id.currency_id.id,
            "date_from": fields.Date.to_string(self.date_from),
            "date_to": fields.Date.to_string(self.date_to),
            "cmp_from": cmp_from and fields.Date.to_string(cmp_from),
            "cmp_to": cmp_to and fields.Date.to_string(cmp_to),
            "show_accounts": self.show_accounts,
            "posted_only": self.posted_only,
            "company_ids": companies.ids,
        }
        return data

    def action_print_pdf(self):
        return self.env.ref("arco_financial_statements.action_report_financial_statement").report_action(
            self, data=self._report_data()
        )

    def action_view_html(self):
        return self.env.ref("arco_financial_statements.action_report_financial_statement_html").report_action(
            self, data=self._report_data()
        )


class ReportArcoFinancialStatement(models.AbstractModel):
    _name = "report.arco_financial_statements.report_financial_statement"
    _description = "Financial statement report"

    @api.model
    def _get_report_values(self, docids, data=None):
        if not data:
            wizard = self.env["arco.financial.statement.wizard"].browse(docids)
            data = wizard._report_data()
        engine = self.env["arco.financial.statement"]
        companies = self.env["res.company"].browse(data["company_ids"])
        d_from = fields.Date.to_date(data["date_from"])
        d_to = fields.Date.to_date(data["date_to"])
        c_from = data.get("cmp_from") and fields.Date.to_date(data["cmp_from"])
        c_to = data.get("cmp_to") and fields.Date.to_date(data["cmp_to"])
        posted = data.get("posted_only", True)
        vals = {"data": data, "currency": self.env["res.currency"].browse(data["currency_id"]),
                "d_from": d_from, "d_to": d_to, "c_from": c_from, "c_to": c_to}
        if "pl" in data["statements"]:
            vals["pl"] = engine.profit_and_loss(companies, d_from, d_to, posted)
            vals["pl_cmp"] = c_from and engine.profit_and_loss(companies, c_from, c_to, posted)
        if "bs" in data["statements"]:
            vals["bs"] = engine.balance_sheet(companies, d_to, posted)
            vals["bs_cmp"] = c_to and engine.balance_sheet(companies, c_to, posted)
        if "cf" in data["statements"]:
            vals["cf"] = engine.cash_flow(companies, d_from, d_to, posted)
            vals["cf_cmp"] = c_from and engine.cash_flow(companies, c_from, c_to, posted)
        vals["rows"] = self._rows
        vals["docs"] = companies[:1]
        vals["company"] = companies[:1]
        return vals

    @staticmethod
    def _rows(section, cmp_section):
        """Merge current and comparative account lines: [(code, name, current, comparative)]."""
        merged = {}
        for line in section["lines"]:
            merged[(line["code"], line["name"])] = [line["amount"], 0.0]
        for line in (cmp_section or {}).get("lines", []):
            merged.setdefault((line["code"], line["name"]), [0.0, 0.0])[1] = line["amount"]
        return [(k[0], k[1], v[0], v[1]) for k, v in sorted(merged.items(), key=lambda kv: (kv[0][0] or "~", kv[0][1]))]

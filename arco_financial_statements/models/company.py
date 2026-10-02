from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    arco_monthly_pl_enabled = fields.Boolean("Email monthly P&L to management")
    arco_monthly_pl_partner_ids = fields.Many2many(
        "res.partner", "arco_company_pl_partner_rel", "company_id", "partner_id",
        string="Monthly P&L Recipients",
    )

    @api.model
    def _cron_arco_monthly_pl(self):
        """1st of each month: previous month P&L (with prior-year comparative) as PDF to management."""
        today = fields.Date.context_today(self)
        date_to = today.replace(day=1) - relativedelta(days=1)
        date_from = date_to.replace(day=1)
        template = self.env.ref("arco_financial_statements.mail_template_monthly_pl")
        for company in self.search([("arco_monthly_pl_enabled", "=", True), ("parent_id", "=", False)]):
            if not company.arco_monthly_pl_partner_ids:
                continue
            wizard = self.env["arco.financial.statement.wizard"].with_company(company).create({
                "statement": "pl",
                "date_from": date_from,
                "date_to": date_to,
                "comparison": "prior_year",
                "company_id": company.id,
            })
            pdf, _fmt = self.env["ir.actions.report"].with_company(company)._render_qweb_pdf(
                "arco_financial_statements.action_report_financial_statement", wizard.ids,
                data=wizard._report_data(),
            )
            attachment = self.env["ir.attachment"].create({
                "name": _("P&L %s.pdf", date_to.strftime("%B %Y")),
                "raw": pdf,
                "mimetype": "application/pdf",
                "res_model": "res.company",
                "res_id": company.id,
            })
            template.with_context(
                arco_period=date_to.strftime("%B %Y"),
            ).send_mail(
                company.id,
                force_send=True,
                email_values={
                    "recipient_ids": [(6, 0, company.arco_monthly_pl_partner_ids.ids)],
                    "attachment_ids": [(4, attachment.id)],
                },
            )


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    arco_monthly_pl_enabled = fields.Boolean(related="company_id.arco_monthly_pl_enabled", readonly=False)
    arco_monthly_pl_partner_ids = fields.Many2many(
        related="company_id.arco_monthly_pl_partner_ids", readonly=False
    )

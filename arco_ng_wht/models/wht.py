from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ArcoWhtCategory(models.Model):
    """Transaction types in the WHT regulations (supply, contract, consultancy, rent...).
    Rates are held on the linked taxes so they can follow regulatory changes without code."""

    _name = "arco.wht.category"
    _description = "Withholding Tax Category"
    _order = "sequence, name"

    name = fields.Char(required=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    purchase_tax_id = fields.Many2one(
        "account.tax",
        string="WHT on Vendor Bills",
        domain="[('type_tax_use', '=', 'purchase'), ('amount', '<', 0)]",
        help="Negative-rate tax deducted at source from vendor payments",
    )
    sale_tax_id = fields.Many2one(
        "account.tax",
        string="WHT Suffered on Invoices",
        domain="[('type_tax_use', '=', 'sale'), ('amount', '<', 0)]",
        help="Negative-rate tax deducted by customers (WHT credit)",
    )
    authority = fields.Selection(
        [("federal", "Federal (NRS/FIRS)"), ("state", "State IRS")], default="federal"
    )
    active = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs._arco_flag_taxes()
        return recs

    def write(self, vals):
        res = super().write(vals)
        if {"purchase_tax_id", "sale_tax_id"} & set(vals):
            self._arco_flag_taxes()
        return res

    def _arco_flag_taxes(self):
        (self.mapped("purchase_tax_id") | self.mapped("sale_tax_id")).write({"arco_tax_kind": "wht"})


class AccountTax(models.Model):
    _inherit = "account.tax"

    arco_tax_kind = fields.Selection(
        [("wht", "Withholding Tax"), ("ncd", "NCD Levy (1% NCDF)")],
        string="Deduction at Source",
        help="Marks negative taxes that are deductions at source, so WHT and NCD are reported separately.",
    )


class ResPartner(models.Model):
    _inherit = "res.partner"

    arco_wht_category_id = fields.Many2one(
        "arco.wht.category", string="WHT Category", company_dependent=True, tracking=True
    )
    arco_wht_exempt = fields.Boolean("WHT Exempt", tracking=True)


class AccountMove(models.Model):
    _inherit = "account.move"

    arco_wht_amount = fields.Monetary("WHT Deducted", compute="_compute_arco_wht_amount", store=True)
    arco_wht_cert_no = fields.Char("WHT Credit Note No.", tracking=True, copy=False)
    arco_wht_cert_date = fields.Date("WHT Credit Note Date", tracking=True, copy=False)
    arco_wht_cert_state = fields.Selection(
        [("na", "Not applicable"), ("expected", "Expected"), ("received", "Received")],
        string="WHT Credit Note",
        compute="_compute_arco_wht_cert_state",
        store=True,
    )

    @api.depends("line_ids.tax_line_id", "line_ids.balance", "line_ids.tax_line_id.arco_tax_kind")
    def _compute_arco_wht_amount(self):
        for move in self:
            wht_lines = move.line_ids.filtered(lambda l: l.tax_line_id.arco_tax_kind == "wht")
            move.arco_wht_amount = abs(sum(wht_lines.mapped("amount_currency")))

    @api.depends("arco_wht_amount", "arco_wht_cert_no", "move_type", "state")
    def _compute_arco_wht_cert_state(self):
        for move in self:
            if move.move_type != "out_invoice" or not move.arco_wht_amount or move.state != "posted":
                move.arco_wht_cert_state = "na"
            else:
                move.arco_wht_cert_state = "received" if move.arco_wht_cert_no else "expected"

    def _arco_wht_tax_for(self, partner):
        partner = partner.commercial_partner_id.with_company(self.company_id)
        if partner.arco_wht_exempt or not partner.arco_wht_category_id:
            return self.env["account.tax"]
        cat = partner.arco_wht_category_id
        if self.move_type in ("in_invoice", "in_refund"):
            return cat.purchase_tax_id
        if self.move_type in ("out_invoice", "out_refund"):
            return cat.sale_tax_id
        return self.env["account.tax"]

    def action_arco_apply_wht(self):
        for move in self:
            if move.state != "draft":
                raise UserError(_("WHT can only be applied on draft documents."))
            tax = move._arco_wht_tax_for(move.partner_id)
            if not tax:
                continue
            for line in move.invoice_line_ids.filtered(lambda l: l.display_type == "product"):
                if not (line.tax_ids & tax) and not line.tax_ids.filtered(lambda t: t.arco_tax_kind == "wht"):
                    line.tax_ids = [(4, tax.id)]
        return True

    def action_post(self):
        # automatic WHT on vendor bills when the company has opted in
        for move in self.filtered(
            lambda m: m.move_type in ("in_invoice", "in_refund") and m.company_id.arco_wht_auto_apply
        ):
            move.action_arco_apply_wht()
        return super().action_post()


class ResCompany(models.Model):
    _inherit = "res.company"

    arco_wht_auto_apply = fields.Boolean(
        "Auto-apply WHT on vendor bills", default=True,
        help="On posting, add the vendor's WHT category tax to bill lines that have no WHT yet.",
    )


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    arco_wht_auto_apply = fields.Boolean(related="company_id.arco_wht_auto_apply", readonly=False)

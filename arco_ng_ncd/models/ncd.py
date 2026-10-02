from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


def _free_code(env, company, start):
    Account = env["account.account"].with_company(company)
    code = int(start)
    while Account.search_count([("code", "=", str(code)), ("company_ids", "in", company.id)]):
        code += 1
    return str(code)


def _get_or_create_account(env, company, name, account_type, start_code):
    Account = env["account.account"].with_company(company)
    acc = Account.search([("name", "=", name), ("company_ids", "in", company.id)], limit=1)
    if not acc:
        acc = Account.create({
            "name": name,
            "code": _free_code(env, company, start_code),
            "account_type": account_type,
            "company_ids": [Command.link(company.id)],
        })
    return acc


def setup_ncd_taxes(env, company):
    """Create the NCDF accounts, tax group and the two -1% deduction-at-source taxes."""
    if company.arco_ncd_sale_tax_id and company.arco_ncd_purchase_tax_id:
        return
    payable = _get_or_create_account(env, company, "NCDF Levy Payable (NCDMB)", "liability_current", 217500)
    expense = _get_or_create_account(env, company, "NCD Levy (1% NCDF) Expense", "expense", 629500)
    group = env["account.tax.group"].search(
        [("name", "=", "NCD Levy"), ("company_id", "=", company.id)], limit=1
    ) or env["account.tax.group"].create({"name": "NCD Levy", "company_id": company.id, "sequence": 90})

    def _tax(name, use, account):
        rep = [
            Command.create({"repartition_type": "base"}),
            Command.create({"repartition_type": "tax", "account_id": account.id}),
        ]
        return env["account.tax"].create({
            "name": name,
            "description": "NCD 1%",
            "amount_type": "percent",
            "amount": -1.0,
            "type_tax_use": use,
            "company_id": company.id,
            "tax_group_id": group.id,
            "arco_tax_kind": "ncd",
            "invoice_repartition_line_ids": rep,
            "refund_repartition_line_ids": [
                Command.create({"repartition_type": "base"}),
                Command.create({"repartition_type": "tax", "account_id": account.id}),
            ],
        })

    company.write({
        "arco_ncd_sale_tax_id": company.arco_ncd_sale_tax_id.id
        or _tax("NCD 1% deducted by customer (NCDF)", "sale", expense).id,
        "arco_ncd_purchase_tax_id": company.arco_ncd_purchase_tax_id.id
        or _tax("NCD 1% deducted from vendor (NCDF)", "purchase", payable).id,
    })


class ResCompany(models.Model):
    _inherit = "res.company"

    arco_ncd_auto_apply = fields.Boolean("Auto-apply NCD levy on posting", default=True)
    arco_ncd_sale_tax_id = fields.Many2one(
        "account.tax", string="NCD Tax (customer invoices)",
        domain="[('type_tax_use', '=', 'sale'), ('arco_tax_kind', '=', 'ncd')]",
    )
    arco_ncd_purchase_tax_id = fields.Many2one(
        "account.tax", string="NCD Tax (vendor bills)",
        domain="[('type_tax_use', '=', 'purchase'), ('arco_tax_kind', '=', 'ncd')]",
    )


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    arco_ncd_auto_apply = fields.Boolean(related="company_id.arco_ncd_auto_apply", readonly=False)
    arco_ncd_sale_tax_id = fields.Many2one(related="company_id.arco_ncd_sale_tax_id", readonly=False)
    arco_ncd_purchase_tax_id = fields.Many2one(related="company_id.arco_ncd_purchase_tax_id", readonly=False)

    def action_arco_setup_ncd(self):
        setup_ncd_taxes(self.env, self.company_id.root_id)
        return True


class ResPartner(models.Model):
    _inherit = "res.partner"

    arco_ncd_applicable = fields.Boolean(
        "NCD Levy Applicable",
        tracking=True,
        help="Customer: upstream operator that deducts the 1% NCDF levy from ARCO invoices.\n"
        "Vendor: subcontractor on upstream work from whom ARCO deducts 1% NCDF.",
    )


class AccountMove(models.Model):
    _inherit = "account.move"

    arco_ncd_applicable = fields.Boolean(
        "NCD Levy Applies",
        compute="_compute_arco_ncd_applicable",
        store=True,
        readonly=False,
        help="Defaults from the partner; untick for non-upstream contracts.",
    )
    arco_ncd_amount = fields.Monetary("NCD Levy", compute="_compute_arco_ncd_amount", store=True)
    arco_ncd_contract_ref = fields.Char("Contract / PO No. (NCD)", tracking=True, copy=False)

    @api.depends("partner_id")
    def _compute_arco_ncd_applicable(self):
        for move in self:
            move.arco_ncd_applicable = bool(
                move.is_invoice(include_receipts=False)
                and move.partner_id.commercial_partner_id.arco_ncd_applicable
            )

    @api.depends("line_ids.tax_line_id", "line_ids.balance", "line_ids.tax_line_id.arco_tax_kind")
    def _compute_arco_ncd_amount(self):
        for move in self:
            lines = move.line_ids.filtered(lambda l: l.tax_line_id.arco_tax_kind == "ncd")
            move.arco_ncd_amount = abs(sum(lines.mapped("amount_currency")))

    def _arco_ncd_tax(self):
        self.ensure_one()
        company = self.company_id.root_id
        if self.move_type in ("out_invoice", "out_refund"):
            return company.arco_ncd_sale_tax_id
        if self.move_type in ("in_invoice", "in_refund"):
            return company.arco_ncd_purchase_tax_id
        return self.env["account.tax"]

    def action_arco_apply_ncd(self):
        for move in self:
            if move.state != "draft":
                raise UserError(_("The NCD levy can only be applied on draft documents."))
            tax = move._arco_ncd_tax()
            if not tax:
                raise UserError(_("Configure the NCD taxes in Accounting settings first."))
            for line in move.invoice_line_ids.filtered(lambda l: l.display_type == "product"):
                if not line.tax_ids.filtered(lambda t: t.arco_tax_kind == "ncd"):
                    line.tax_ids = [Command.link(tax.id)]
            if not move.arco_ncd_applicable:
                move.arco_ncd_applicable = True
        return True

    def action_arco_remove_ncd(self):
        for move in self.filtered(lambda m: m.state == "draft"):
            for line in move.invoice_line_ids:
                ncd = line.tax_ids.filtered(lambda t: t.arco_tax_kind == "ncd")
                if ncd:
                    line.tax_ids = [Command.unlink(t.id) for t in ncd]
            move.arco_ncd_applicable = False
        return True

    def action_post(self):
        for move in self.filtered(
            lambda m: m.is_invoice(include_receipts=False)
            and m.arco_ncd_applicable
            and m.company_id.root_id.arco_ncd_auto_apply
            and m._arco_ncd_tax()
        ):
            move.action_arco_apply_ncd()
        return super().action_post()


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    arco_ncd_remittance_id = fields.Many2one(
        "arco.ncd.remittance", string="NCD Remittance", copy=False, index="btree_not_null", readonly=True
    )


class ArcoNcdRemittance(models.Model):
    """Monthly (or per-contract) payment of NCD deducted from vendors to the NCDF (NCDMB)."""

    _name = "arco.ncd.remittance"
    _description = "NCD Levy Remittance"
    _inherit = ["mail.thread"]
    _order = "date_to desc, id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    journal_id = fields.Many2one(
        "account.journal", string="Paid From",
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
    )
    payment_date = fields.Date(default=fields.Date.context_today)
    ncdmb_receipt = fields.Char("NCDMB Receipt / Ref.", tracking=True)
    line_ids = fields.One2many("account.move.line", "arco_ncd_remittance_id", string="NCD Deductions")
    amount = fields.Monetary(compute="_compute_amount", store=True)
    base_amount = fields.Monetary("Contract Value (Base)", compute="_compute_amount", store=True)
    move_id = fields.Many2one("account.move", string="Remittance Entry", readonly=True, copy=False)
    state = fields.Selection(
        [("draft", "Draft"), ("posted", "Remitted"), ("cancel", "Cancelled")], default="draft", tracking=True
    )

    @api.depends("line_ids.balance", "line_ids.tax_base_amount")
    def _compute_amount(self):
        for rec in self:
            rec.amount = -sum(rec.line_ids.mapped("balance"))
            rec.base_amount = sum(abs(b) for b in rec.line_ids.mapped("tax_base_amount"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("arco.ncd.remittance") or "New"
        return super().create(vals_list)

    def _unremitted_domain(self):
        self.ensure_one()
        return [
            ("company_id", "child_of", self.company_id.root_id.id),
            ("parent_state", "=", "posted"),
            ("tax_line_id.arco_tax_kind", "=", "ncd"),
            ("tax_line_id.type_tax_use", "=", "purchase"),
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
            ("arco_ncd_remittance_id", "=", False),
        ]

    def action_compute(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only draft remittances can be recomputed."))
            rec.line_ids.write({"arco_ncd_remittance_id": False})
            self.env["account.move.line"].search(rec._unremitted_domain()).write(
                {"arco_ncd_remittance_id": rec.id}
            )
        return True

    def action_post(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_("No NCD deductions to remit."))
            if not rec.journal_id:
                raise UserError(_("Select the bank journal the levy is paid from."))
            by_account = {}
            for line in rec.line_ids:
                by_account[line.account_id] = by_account.get(line.account_id, 0.0) - line.balance
            bank_account = rec.journal_id.default_account_id
            move_lines = [
                Command.create({
                    "name": _("NCD levy remittance %s", rec.name),
                    "account_id": account.id,
                    "debit": amount,
                    "credit": 0.0,
                })
                for account, amount in by_account.items()
            ]
            move_lines.append(Command.create({
                "name": _("NCDF payment %s", rec.ncdmb_receipt or rec.name),
                "account_id": bank_account.id,
                "debit": 0.0,
                "credit": rec.amount,
            }))
            move = self.env["account.move"].create({
                "move_type": "entry",
                "journal_id": rec.journal_id.id,
                "date": rec.payment_date,
                "ref": _("NCDF remittance %(name)s (%(start)s - %(end)s)", name=rec.name,
                         start=rec.date_from, end=rec.date_to),
                "line_ids": move_lines,
            })
            move.action_post()
            rec.write({"move_id": move.id, "state": "posted"})
        return True

    def action_cancel(self):
        for rec in self:
            if rec.move_id and rec.move_id.state == "posted":
                rec.move_id._reverse_moves(cancel=True)
            rec.line_ids.write({"arco_ncd_remittance_id": False})
            rec.state = "cancel"
        return True

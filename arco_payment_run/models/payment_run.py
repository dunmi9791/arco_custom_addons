import base64
import csv
import io

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ArcoPaymentRun(models.Model):
    """Payment voucher / payment batch.

    SMERP flow: Vendor Invoice Processing -> Payment Approval -> Vendor Payment.
    Finance selects posted, unpaid vendor bills, the voucher goes through the
    authorization matrix, and only then are the payments created and the bank file produced.
    """

    _name = "arco.payment.run"
    _description = "Payment Voucher / Payment Run"
    _inherit = ["mail.thread", "mail.activity.mixin", "tier.validation"]
    _order = "id desc"
    _state_from = ["submitted"]
    _state_to = ["approved"]
    _cancel_state = "rejected"
    _tier_validation_manual_config = False

    name = fields.Char("Voucher No.", default="New", readonly=True, copy=False, tracking=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Awaiting Approval"),
            ("approved", "Approved"),
            ("paid", "Paid"),
            ("rejected", "Rejected"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        tracking=True,
        copy=False,
        index=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    journal_id = fields.Many2one(
        "account.journal",
        string="Pay From",
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
        required=True,
        tracking=True,
    )
    payment_date = fields.Date(default=fields.Date.context_today, required=True, tracking=True)
    due_date_limit = fields.Date("Bills Due On/Before", default=fields.Date.context_today)
    partner_ids = fields.Many2many("res.partner", string="Only These Vendors")
    narration = fields.Char("Narration", help="Appears on the bank upload file and remittance advice")
    prepared_by = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True)
    line_ids = fields.One2many("arco.payment.run.line", "run_id", copy=False)
    amount_total = fields.Monetary(compute="_compute_amount_total", store=True, string="Total to Pay")
    payment_ids = fields.Many2many("account.payment", string="Payments", copy=False, readonly=True)
    payment_count = fields.Integer(compute="_compute_payment_count")
    bank_file_id = fields.Many2one("ir.attachment", string="Bank File", copy=False, readonly=True)

    @api.depends("line_ids.amount_to_pay")
    def _compute_amount_total(self):
        for rec in self:
            rec.amount_total = sum(rec.line_ids.mapped("amount_to_pay"))

    def _compute_payment_count(self):
        for rec in self:
            rec.payment_count = len(rec.payment_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("arco.payment.run") or "New"
        return super().create(vals_list)

    # ------------------------------------------------------------ selection
    def _due_bills_domain(self):
        self.ensure_one()
        domain = [
            ("company_id", "=", self.company_id.id),
            ("move_type", "=", "in_invoice"),
            ("state", "=", "posted"),
            ("payment_state", "in", ("not_paid", "partial")),
        ]
        if self.due_date_limit:
            domain.append(("invoice_date_due", "<=", self.due_date_limit))
        if self.partner_ids:
            domain.append(("commercial_partner_id", "in", self.partner_ids.ids))
        return domain

    def action_load_due_bills(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Bills can only be loaded on a draft voucher."))
            already = rec.line_ids.move_id
            # bills already sitting on another open voucher are skipped
            busy = self.env["arco.payment.run.line"].search([
                ("run_id.state", "in", ("draft", "submitted", "approved")),
                ("run_id", "!=", rec.id),
            ]).move_id
            bills = self.env["account.move"].search(rec._due_bills_domain(), order="invoice_date_due, id").filtered(
                lambda m: not m._arco_is_expense_report()
            )
            vals = [
                {"run_id": rec.id, "move_id": bill.id, "amount_to_pay": abs(bill.amount_residual_signed)}
                for bill in bills - already - busy
            ]
            self.env["arco.payment.run.line"].create(vals)
        return True

    # ------------------------------------------------------------ workflow
    def action_submit(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_("Add at least one bill to %s before submitting.", rec.name))
            rec.line_ids._check_amounts()
            rec.state = "submitted"
            rec.request_validation()
        return True

    def _validate_tier(self, tiers=False):
        res = super()._validate_tier(tiers)
        for rec in self.filtered(lambda r: r.state == "submitted" and r.validated):
            rec.state = "approved"
            rec.message_post(body=_("Payment voucher fully approved and released for payment."))
        return res

    def _rejected_tier(self, tiers=False):
        res = super()._rejected_tier(tiers)
        self.filtered(lambda r: r.state == "submitted").write({"state": "rejected"})
        return res

    def action_draft(self):
        self.restart_validation()
        self.write({"state": "draft"})

    def action_cancel(self):
        if any(r.state == "paid" for r in self):
            raise UserError(_("A paid voucher cannot be cancelled; cancel the payments instead."))
        self.restart_validation()
        self.write({"state": "cancel"})

    def action_pay(self):
        """Create one payment per bill through the standard register-payment wizard so that
        reconciliation, partial payments and currency handling stay standard."""
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("%s must be approved before payment.", rec.name))
            payments = self.env["account.payment"]
            for line in rec.line_ids.filtered(lambda l: not l.payment_id and l.amount_to_pay > 0):
                wizard = (
                    self.env["account.payment.register"]
                    .with_context(
                        active_model="account.move",
                        active_ids=line.move_id.ids,
                        arco_payment_run=True,
                    )
                    .create({
                        "journal_id": rec.journal_id.id,
                        "payment_date": rec.payment_date,
                        "amount": line.amount_to_pay,
                        "currency_id": rec.currency_id.id,
                        "communication": line.move_id.ref or line.move_id.name,
                        "payment_difference_handling": "open",
                        **({"partner_bank_id": line.partner_bank_id.id} if line.partner_bank_id else {}),
                    })
                )
                payment = wizard.with_context(arco_payment_run=True)._create_payments()
                line.payment_id = payment[:1]
                payments |= payment
            rec.payment_ids = [(4, p.id) for p in payments]
            rec.state = "paid"
            rec.message_post(body=_("%s payment(s) created.", len(payments)))
        return True

    def action_view_payments(self):
        action = self.env["ir.actions.act_window"]._for_xml_id("account.action_account_payments_payable")
        action["domain"] = [("id", "in", self.payment_ids.ids)]
        action["context"] = {}
        return action

    # ------------------------------------------------------------ bank file
    def _bank_file_rows(self):
        self.ensure_one()
        rows = []
        for i, line in enumerate(self.line_ids.filtered(lambda l: l.amount_to_pay > 0), start=1):
            bank = line.partner_bank_id
            rows.append([
                i,
                (bank.acc_holder_name or line.partner_id.name or "").strip(),
                bank.acc_number or "",
                bank.bank_id.name or "",
                bank.bank_id.bic or "",
                "%.2f" % line.amount_to_pay,
                (self.narration or line.move_id.ref or line.move_id.name or "")[:30],
                self.name,
            ])
        return rows

    def action_export_bank_file(self):
        self.ensure_one()
        if self.state not in ("approved", "paid"):
            raise UserError(_("Only approved vouchers can be exported to the bank."))
        missing = self.line_ids.filtered(lambda l: not l.partner_bank_id)
        if missing:
            raise ValidationError(_(
                "Set a beneficiary bank account for: %s", ", ".join(missing.partner_id.mapped("name"))
            ))
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "S/N", "Beneficiary Name", "Account Number", "Bank Name",
            "Bank Code (CBN/NIP)", "Amount", "Narration", "Reference",
        ])
        writer.writerows(self._bank_file_rows())
        att = self.env["ir.attachment"].create({
            "name": f"{self.name.replace('/', '_')}_bank_upload.csv",
            "datas": base64.b64encode(buf.getvalue().encode("utf-8")),
            "res_model": self._name,
            "res_id": self.id,
            "mimetype": "text/csv",
        })
        self.bank_file_id = att
        self.message_post(body=_("Bank upload file generated."), attachment_ids=att.ids)
        return {"type": "ir.actions.act_url", "url": f"/web/content/{att.id}?download=true", "target": "self"}

    def action_send_remittance(self):
        template = self.env.ref("arco_payment_run.mail_template_remittance_advice")
        for rec in self:
            if rec.state != "paid":
                raise UserError(_("Remittance advice is sent after payment."))
            for line in rec.line_ids.filtered("payment_id"):
                template.send_mail(line.id, force_send=False)
            rec.message_post(body=_("Remittance advice queued for %s vendor(s).", len(rec.line_ids)))
        return True


class ArcoPaymentRunLine(models.Model):
    _name = "arco.payment.run.line"
    _description = "Payment Voucher Line"
    _order = "run_id, id"

    run_id = fields.Many2one("arco.payment.run", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="run_id.company_id", store=True)
    currency_id = fields.Many2one(related="run_id.currency_id")
    move_id = fields.Many2one(
        "account.move",
        string="Vendor Bill",
        required=True,
        domain="[('move_type', '=', 'in_invoice'), ('state', '=', 'posted'), "
        "('payment_state', 'in', ('not_paid', 'partial')), ('company_id', '=', company_id)]",
    )
    partner_id = fields.Many2one(related="move_id.commercial_partner_id", store=True, string="Vendor")
    bill_ref = fields.Char(related="move_id.ref", string="Vendor Ref.")
    invoice_date_due = fields.Date(related="move_id.invoice_date_due", string="Due Date")
    amount_residual = fields.Monetary(
        compute="_compute_amount_residual", string="Outstanding", currency_field="currency_id"
    )
    amount_to_pay = fields.Monetary("Amount to Pay", currency_field="currency_id")
    partner_bank_id = fields.Many2one(
        "res.partner.bank",
        string="Beneficiary Account",
        domain="[('partner_id', '=', partner_id)]",
        compute="_compute_partner_bank_id",
        store=True,
        readonly=False,
    )
    payment_id = fields.Many2one("account.payment", readonly=True, copy=False)

    _sql_constraints = [
        ("bill_unique", "unique(run_id, move_id)", "A bill can appear only once on a voucher."),
    ]

    @api.depends("move_id.amount_residual_signed")
    def _compute_amount_residual(self):
        for line in self:
            line.amount_residual = abs(line.move_id.amount_residual_signed)

    @api.depends("move_id")
    def _compute_partner_bank_id(self):
        for line in self:
            line.partner_bank_id = line.move_id.partner_bank_id or line.partner_id.bank_ids[:1]

    @api.onchange("move_id")
    def _onchange_move_id(self):
        if self.move_id:
            self.amount_to_pay = abs(self.move_id.amount_residual_signed)

    def _check_amounts(self):
        for line in self:
            if line.amount_to_pay <= 0:
                raise ValidationError(_("Amount to pay must be positive (%s).", line.move_id.name))
            if line.currency_id.compare_amounts(line.amount_to_pay, line.amount_residual) > 0:
                raise ValidationError(_(
                    "%(bill)s: amount to pay exceeds the outstanding balance.", bill=line.move_id.name
                ))


class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    def action_create_payments(self):
        company = self.company_id or self.env.company
        if (
            company.arco_require_payment_voucher
            and not self.env.context.get("arco_payment_run")
            and self.payment_type == "outbound"
            and any(m.move_type == "in_invoice" and not m._arco_is_expense_report() for m in self.line_ids.move_id)
        ):
            raise UserError(_(
                "Vendor bills are paid through an approved Payment Voucher "
                "(Accounting > Vendors > Payment Vouchers)."
            ))
        # payments coming from the register wizard were checked above (bills) or are
        # employee reimbursements / refunds, which follow their own approval flows
        return super(AccountPaymentRegister, self.with_context(arco_payment_checked=True)).action_create_payments()

    def _create_payments(self):
        return super(AccountPaymentRegister, self.with_context(arco_payment_checked=True))._create_payments()


class AccountMove(models.Model):
    _inherit = "account.move"

    def _arco_is_expense_report(self):
        """Employee expense reports (hr_expense) follow their own approval flow."""
        self.ensure_one()
        return bool("expense_sheet_id" in self._fields and self.expense_sheet_id)


class AccountPayment(models.Model):
    _inherit = "account.payment"

    def _arco_needs_voucher(self):
        self.ensure_one()
        ctx = self.env.context
        if ctx.get("arco_payment_run") or ctx.get("arco_payment_checked"):
            return False
        if not self.company_id.arco_require_payment_voucher:
            return False
        if self.payment_type != "outbound" or self.partner_type != "supplier":
            return False
        if "expense_sheet_id" in self._fields and self.expense_sheet_id:
            return False
        return not self.env.user.has_group("arco_base.group_arco_finance_director")

    def action_post(self):
        if any(pay._arco_needs_voucher() for pay in self):
            raise UserError(_(
                "Direct vendor payments need an approved Payment Voucher. "
                "Only the Finance Director can post an ad-hoc vendor payment."
            ))
        return super().action_post()


class ResCompany(models.Model):
    _inherit = "res.company"

    arco_require_payment_voucher = fields.Boolean(
        "Vendor payments require an approved Payment Voucher", default=True
    )


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    arco_require_payment_voucher = fields.Boolean(
        related="company_id.arco_require_payment_voucher", readonly=False
    )


class TierDefinition(models.Model):
    _inherit = "tier.definition"

    @api.model
    def _get_tier_validation_model_names(self):
        res = super()._get_tier_validation_model_names()
        res.append("arco.payment.run")
        return res

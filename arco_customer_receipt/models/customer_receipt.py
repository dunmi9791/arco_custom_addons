from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ArcoCustomerReceipt(models.Model):
    """Customer receipt application.

    Nigerian customers (IOCs, NOCs) often settle several invoices with one transfer, pay part of
    an invoice, and deduct WHT and the NCD levy at source. Standard "Register Payment" handles
    one invoice or full settlements; this voucher records the receipt once and applies it
    line by line, keeping the unapplied balance on the customer account.
    """

    _name = "arco.customer.receipt"
    _description = "Customer Receipt"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char("Receipt No.", default="New", readonly=True, copy=False)
    state = fields.Selection(
        [("draft", "Draft"), ("posted", "Posted"), ("cancel", "Cancelled")], default="draft", tracking=True
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    partner_id = fields.Many2one(
        "res.partner", string="Customer", required=True, tracking=True,
        domain="[('parent_id', '=', False)]",
    )
    date = fields.Date(default=fields.Date.context_today, required=True, tracking=True)
    journal_id = fields.Many2one(
        "account.journal", string="Received In", required=True,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
    )
    amount = fields.Monetary("Amount Received", required=True, tracking=True)
    bank_reference = fields.Char("Bank Ref. / Teller No.", tracking=True)
    line_ids = fields.One2many("arco.customer.receipt.line", "receipt_id", copy=False)
    amount_allocated = fields.Monetary(compute="_compute_totals", store=True)
    amount_deducted = fields.Monetary("WHT / NCD Deducted", compute="_compute_totals", store=True)
    amount_unallocated = fields.Monetary("Unapplied (on account)", compute="_compute_totals", store=True)
    payment_ids = fields.Many2many("account.payment", string="Payments", readonly=True, copy=False)
    payment_count = fields.Integer(compute="_compute_payment_count")

    @api.depends("amount", "line_ids.amount_allocated", "line_ids.deduction_amount")
    def _compute_totals(self):
        for rec in self:
            rec.amount_allocated = sum(rec.line_ids.mapped("amount_allocated"))
            rec.amount_deducted = sum(rec.line_ids.mapped("deduction_amount"))
            rec.amount_unallocated = rec.amount - rec.amount_allocated

    def _compute_payment_count(self):
        for rec in self:
            rec.payment_count = len(rec.payment_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("arco.customer.receipt") or "New"
        return super().create(vals_list)

    @api.constrains("amount", "line_ids")
    def _check_allocation(self):
        for rec in self:
            if rec.currency_id.compare_amounts(rec.amount_allocated, rec.amount) > 0:
                raise ValidationError(_("Allocated amount exceeds the amount received on %s.", rec.name))

    # -------------------------------------------------------------- lines
    def _open_invoices(self):
        self.ensure_one()
        return self.env["account.move"].search([
            ("company_id", "=", self.company_id.id),
            ("commercial_partner_id", "=", self.partner_id.commercial_partner_id.id),
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("payment_state", "in", ("not_paid", "partial")),
        ], order="invoice_date_due, invoice_date, id")

    def action_load_invoices(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only draft receipts can be changed."))
            existing = rec.line_ids.move_id
            self.env["arco.customer.receipt.line"].create([
                {"receipt_id": rec.id, "move_id": inv.id} for inv in rec._open_invoices() - existing
            ])
        return True

    def action_auto_allocate(self):
        """First in, first out: oldest due invoice is settled first."""
        for rec in self:
            if not rec.line_ids:
                rec.action_load_invoices()
            remaining = rec.amount
            for line in rec.line_ids.sorted(lambda l: (l.invoice_date_due or fields.Date.today(), l.id)):
                due = line.amount_residual - line.deduction_amount
                alloc = max(min(due, remaining), 0.0)
                line.amount_allocated = alloc
                remaining -= alloc
        return True

    def action_clear_allocation(self):
        self.line_ids.write({"amount_allocated": 0.0, "deduction_amount": 0.0})

    # -------------------------------------------------------------- posting
    def _arco_register_payment(self, invoice, amount, deduction=0.0, deduction_account=False, label=False):
        vals = {
            "journal_id": self.journal_id.id,
            "payment_date": self.date,
            "amount": amount,
            "currency_id": self.currency_id.id,
            "communication": self.bank_reference or self.name,
            "payment_difference_handling": "open",
        }
        if deduction:
            vals.update({
                "payment_difference_handling": "reconcile",
                "writeoff_account_id": deduction_account.id,
                "writeoff_label": label or _("WHT/NCD deducted at source"),
            })
        wizard = self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=invoice.ids
        ).create(vals)
        return wizard._create_payments()

    def action_post(self):
        Payment = self.env["account.payment"]
        for rec in self:
            if rec.state != "draft":
                continue
            if rec.currency_id.is_zero(rec.amount):
                raise UserError(_("Enter the amount received."))
            rec._check_allocation()
            payments = Payment
            for line in rec.line_ids.filtered(lambda l: l.amount_allocated > 0 or l.deduction_amount > 0):
                line._check_line()
                payments |= rec._arco_register_payment(
                    line.move_id, line.amount_allocated, line.deduction_amount,
                    line.deduction_account_id, line.deduction_label,
                )
            if rec.currency_id.compare_amounts(rec.amount_unallocated, 0.0) > 0:
                # unapplied cash stays on the customer account (outstanding credit)
                on_account = Payment.create({
                    "payment_type": "inbound",
                    "partner_type": "customer",
                    "partner_id": rec.partner_id.commercial_partner_id.id,
                    "amount": rec.amount_unallocated,
                    "date": rec.date,
                    "journal_id": rec.journal_id.id,
                    "memo": _("%s - unapplied", rec.bank_reference or rec.name),
                    "company_id": rec.company_id.id,
                })
                on_account.action_post()
                payments |= on_account
            rec.write({"payment_ids": [(6, 0, payments.ids)], "state": "posted"})
            rec.message_post(body=_("Receipt applied: %(n)s payment(s) created.", n=len(payments)))
        return True

    def action_cancel(self):
        for rec in self:
            for pay in rec.payment_ids:
                if pay.state != "canceled":
                    pay.move_id.line_ids.remove_move_reconcile()
                    pay.action_draft()
                    pay.action_cancel()
            rec.state = "cancel"
        return True

    def action_draft(self):
        self.filtered(lambda r: r.state == "cancel").write({"state": "draft", "payment_ids": [(5, 0, 0)]})

    def action_view_payments(self):
        action = self.env["ir.actions.act_window"]._for_xml_id("account.action_account_payments")
        action["domain"] = [("id", "in", self.payment_ids.ids)]
        action["context"] = {}
        return action


class ArcoCustomerReceiptLine(models.Model):
    _name = "arco.customer.receipt.line"
    _description = "Customer Receipt Application Line"
    _order = "receipt_id, invoice_date_due, id"

    receipt_id = fields.Many2one("arco.customer.receipt", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="receipt_id.company_id", store=True)
    currency_id = fields.Many2one(related="receipt_id.currency_id")
    move_id = fields.Many2one(
        "account.move", string="Invoice", required=True,
        domain="[('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), "
        "('payment_state', 'in', ('not_paid', 'partial')), ('company_id', '=', company_id)]",
    )
    invoice_date = fields.Date(related="move_id.invoice_date")
    invoice_date_due = fields.Date(related="move_id.invoice_date_due", store=True)
    amount_total = fields.Monetary(compute="_compute_amounts", string="Invoice Total")
    amount_residual = fields.Monetary(compute="_compute_amounts", string="Outstanding")
    amount_allocated = fields.Monetary("Applied")
    deduction_amount = fields.Monetary(
        "Deducted at Source",
        help="WHT and/or NCD levy the customer deducted on payment but which is not on the invoice. "
        "Settles the invoice in full together with the applied amount.",
    )
    deduction_account_id = fields.Many2one(
        "account.account", string="Deduction Account",
        default=lambda self: self.env.company.arco_receipt_deduction_account_id,
    )
    deduction_label = fields.Char("Deduction Label", default="WHT credit / NCD deducted at source")

    @api.depends("move_id.amount_residual_signed", "move_id.amount_total_signed")
    def _compute_amounts(self):
        for line in self:
            line.amount_total = line.move_id.amount_total_signed
            line.amount_residual = line.move_id.amount_residual_signed

    def _check_line(self):
        for line in self:
            if line.amount_allocated < 0 or line.deduction_amount < 0:
                raise ValidationError(_("Amounts must be positive (%s).", line.move_id.name))
            total = line.amount_allocated + line.deduction_amount
            if line.currency_id.compare_amounts(total, line.amount_residual) > 0:
                raise ValidationError(_("%s: applied + deducted exceeds the outstanding balance.", line.move_id.name))
            if line.deduction_amount:
                if not line.deduction_account_id:
                    raise ValidationError(_("%s: set the account for the deduction.", line.move_id.name))
                if line.currency_id.compare_amounts(total, line.amount_residual) != 0:
                    raise ValidationError(_(
                        "%s: when a deduction is recorded the applied amount plus the deduction must "
                        "settle the invoice in full.", line.move_id.name,
                    ))


class ResCompany(models.Model):
    _inherit = "res.company"

    arco_receipt_deduction_account_id = fields.Many2one(
        "account.account", string="Default account for deductions at receipt",
        help="Usually the WHT receivable (credit note) account.",
    )


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    arco_receipt_deduction_account_id = fields.Many2one(
        related="company_id.arco_receipt_deduction_account_id", readonly=False
    )

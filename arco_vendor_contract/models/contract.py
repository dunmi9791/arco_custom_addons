from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ArcoVendorContract(models.Model):
    _name = "arco.vendor.contract"
    _description = "Vendor Contract"
    _inherit = ["portal.mixin", "mail.thread", "mail.activity.mixin", "tier.validation"]
    _order = "id desc"
    _state_from = ["review"]
    _state_to = ["approved"]
    _cancel_state = "rejected"
    _tier_validation_manual_config = False

    name = fields.Char("Contract No.", default="New", readonly=True, copy=False)
    title = fields.Char(required=True, tracking=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("review", "In Review"),
            ("approved", "Approved"),
            ("signing", "Out for Signature"),
            ("active", "Active"),
            ("expired", "Expired"),
            ("terminated", "Terminated"),
            ("rejected", "Rejected"),
            ("cancel", "Cancelled"),
        ],
        default="draft", tracking=True, copy=False, index=True,
    )
    partner_id = fields.Many2one("res.partner", string="Vendor", required=True, tracking=True)
    vendor_signatory_id = fields.Many2one(
        "res.partner", string="Vendor Signatory",
        help="Person who signs for the vendor; receives the signature link.",
    )
    contract_type = fields.Selection(
        [
            ("service", "Service Agreement"),
            ("supply", "Supply Agreement"),
            ("framework", "Framework / Call-off"),
            ("subcontract", "Subcontract"),
            ("lease", "Lease / Hire"),
            ("nda", "NDA"),
            ("other", "Other"),
        ],
        default="service", required=True, tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id, required=True)
    amount = fields.Monetary("Contract Value", tracking=True)
    date_start = fields.Date("Start Date", tracking=True)
    date_end = fields.Date("End Date", tracking=True)
    notice_days = fields.Integer("Expiry Alert (days before)", default=30)
    auto_renew = fields.Boolean()
    responsible_id = fields.Many2one("res.users", string="Procurement Owner", default=lambda self: self.env.user, tracking=True)
    purchase_ids = fields.Many2many(
        "purchase.order", "arco_contract_purchase_rel", "contract_id", "purchase_id", string="Purchase Orders"
    )
    project_id = fields.Many2one("project.project", string="Project")
    document = fields.Binary("Contract Document", attachment=True, copy=False)
    document_name = fields.Char()
    scope = fields.Html("Scope / Key Terms")
    # signatures
    company_signature = fields.Binary("ARCO Signature", copy=False, attachment=True)
    company_signed_by = fields.Many2one("res.users", string="Signed for ARCO by", readonly=True, copy=False)
    company_signed_on = fields.Datetime(readonly=True, copy=False)
    vendor_signature = fields.Binary("Vendor Signature", copy=False, attachment=True)
    vendor_signed_by = fields.Char(readonly=True, copy=False)
    vendor_signed_on = fields.Datetime(readonly=True, copy=False)
    days_to_expiry = fields.Integer(compute="_compute_days_to_expiry")

    def _compute_access_url(self):
        super()._compute_access_url()
        for rec in self:
            rec.access_url = f"/my/contracts/{rec.id}"

    def _compute_days_to_expiry(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.days_to_expiry = (rec.date_end - today).days if rec.date_end else 0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("arco.vendor.contract") or "New"
        return super().create(vals_list)

    # ------------------------------------------------------------ approval
    def action_submit(self):
        for rec in self:
            if not rec.document:
                raise UserError(_("Attach the contract document before sending it for review."))
            rec.state = "review"
            rec.request_validation()
        return True

    def _validate_tier(self, tiers=False):
        res = super()._validate_tier(tiers)
        for rec in self.filtered(lambda r: r.state == "review" and r.validated):
            rec.state = "approved"
            rec.message_post(body=_("Contract approved by Legal, Finance and Executive. Ready for signature."),
                             partner_ids=rec.responsible_id.partner_id.ids)
        return res

    def _rejected_tier(self, tiers=False):
        res = super()._rejected_tier(tiers)
        self.filtered(lambda r: r.state == "review").write({"state": "rejected"})
        return res

    def action_draft(self):
        self.restart_validation()
        self.write({"state": "draft"})

    def action_cancel(self):
        self.restart_validation()
        self.write({"state": "cancel"})

    # ------------------------------------------------------------ signature
    def _signer(self):
        self.ensure_one()
        return self.vendor_signatory_id or self.partner_id

    def action_send_for_signature(self):
        template = self.env.ref("arco_vendor_contract.mail_template_contract_signature")
        for rec in self:
            if rec.state not in ("approved", "signing"):
                raise UserError(_("Only approved contracts can be sent for signature."))
            rec._portal_ensure_token()
            rec.message_subscribe(partner_ids=rec._signer().ids)
            template.send_mail(rec.id, force_send=True, email_values={"recipient_ids": [(6, 0, rec._signer().ids)]})
            rec.state = "signing"
        return True

    def action_company_sign(self):
        """ARCO signatory confirms the signature drawn on the form."""
        for rec in self:
            if rec.state not in ("approved", "signing"):
                raise UserError(_("The contract must be approved before signing."))
            if not rec.company_signature:
                raise UserError(_("Draw the ARCO signature in the Signatures tab first."))
            if not self.env.user.has_group("arco_base.group_arco_md"):
                raise UserError(_("Only Executive Management can sign contracts for ARCO."))
            rec.write({"company_signed_by": self.env.user.id, "company_signed_on": fields.Datetime.now()})
            rec._arco_check_fully_signed()
        return True

    def _arco_vendor_sign(self, name, signature):
        self.ensure_one()
        self.write({"vendor_signed_by": name, "vendor_signature": signature, "vendor_signed_on": fields.Datetime.now()})
        self.message_post(body=_("Contract signed by %s for the vendor.", name))
        self._arco_check_fully_signed()

    def _arco_check_fully_signed(self):
        for rec in self:
            if rec.vendor_signed_on and rec.company_signed_on and rec.state in ("approved", "signing"):
                rec.state = "active"
                pdf = self.env["ir.actions.report"].sudo()._render_qweb_pdf(
                    "arco_vendor_contract.action_report_vendor_contract", rec.ids
                )[0]
                rec.message_post(
                    body=_("Fully signed - contract filed in the repository."),
                    attachments=[(f"{rec.name.replace('/', '_')}_signed.pdf", pdf)],
                )

    def _has_to_be_signed(self):
        self.ensure_one()
        return self.state in ("approved", "signing") and not self.vendor_signed_on

    def action_preview(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "target": "new", "url": self.get_portal_url()}

    def action_terminate(self):
        self.write({"state": "terminated"})

    # ------------------------------------------------------------ repository
    @api.model
    def _cron_contract_expiry(self):
        today = fields.Date.context_today(self)
        for rec in self.search([("state", "=", "active"), ("date_end", "!=", False)]):
            if rec.date_end < today:
                rec.state = "expired"
                rec.message_post(body=_("Contract expired on %s.", rec.date_end))
            elif rec.date_end - timedelta(days=rec.notice_days or 30) <= today and not rec.activity_ids:
                rec.activity_schedule(
                    "mail.mail_activity_data_todo",
                    date_deadline=rec.date_end,
                    user_id=rec.responsible_id.id or self.env.uid,
                    summary=_("Contract %(n)s with %(v)s expires on %(d)s - renew or close out.",
                              n=rec.name, v=rec.partner_id.name, d=rec.date_end),
                )

    def _get_report_base_filename(self):
        self.ensure_one()
        return f"Contract {self.name}"


class TierDefinition(models.Model):
    _inherit = "tier.definition"

    @api.model
    def _get_tier_validation_model_names(self):
        res = super()._get_tier_validation_model_names()
        res.append("arco.vendor.contract")
        return res


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    arco_contract_ids = fields.Many2many(
        "arco.vendor.contract", "arco_contract_purchase_rel", "purchase_id", "contract_id", string="Contracts"
    )

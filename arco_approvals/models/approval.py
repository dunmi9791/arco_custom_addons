from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ArcoApprovalCategory(models.Model):
    _name = "arco.approval.category"
    _description = "Approval Type"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company")
    description = fields.Text()
    request_type = fields.Selection(
        [
            ("generic", "General request"),
            ("spend", "Spending request"),
            ("capex", "CapEx request"),
            ("vendor_onboarding", "Vendor onboarding"),
        ],
        default="generic",
        required=True,
        help="Drives what happens when the request is executed.",
    )
    # what the requester fills in
    has_amount = fields.Selection(
        [("no", "None"), ("optional", "Optional"), ("required", "Required")], default="optional"
    )
    has_partner = fields.Selection(
        [("no", "None"), ("optional", "Optional"), ("required", "Required")], default="no",
        string="Has Vendor/Partner",
    )
    has_period = fields.Selection(
        [("no", "None"), ("optional", "Optional"), ("required", "Required")], default="no",
        string="Has Date Range",
    )
    requires_document = fields.Boolean("Supporting Document Required")
    # approval chain (evaluated by the tier definitions shipped with the module)
    need_supervisor = fields.Boolean("Supervisor Approval", default=True)
    need_dept_head = fields.Boolean("Department Head Approval", default=True)
    need_finance = fields.Boolean("Finance Validation", default=True)
    executive_rule = fields.Selection(
        [("never", "Never"), ("threshold", "Above threshold"), ("always", "Always")],
        default="threshold",
        string="Executive Approval",
    )
    executive_threshold = fields.Monetary(
        default=5000000.0, currency_field="currency_id", help="Company currency"
    )
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    auto_execute = fields.Boolean(
        "Execute on Approval", default=True,
        help="Run the action (e.g. approve the vendor) as soon as the last approval is given.",
    )
    request_count = fields.Integer(compute="_compute_request_count")

    def _compute_request_count(self):
        data = dict(self.env["arco.approval.request"]._read_group(
            [("category_id", "in", self.ids), ("state", "=", "submitted")], ["category_id"], ["__count"]
        ))
        for cat in self:
            cat.request_count = data.get(cat, 0)

    def action_new_request(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "arco.approval.request",
            "view_mode": "form",
            "context": {"default_category_id": self.id},
        }


class ArcoApprovalRequest(models.Model):
    _name = "arco.approval.request"
    _description = "Approval Request"
    _inherit = ["mail.thread", "mail.activity.mixin", "tier.validation"]
    _order = "id desc"
    _state_from = ["submitted"]
    _state_to = ["approved"]
    _cancel_state = "rejected"
    _tier_validation_manual_config = False

    name = fields.Char("Reference", default="New", readonly=True, copy=False)
    title = fields.Char("Subject", required=True, tracking=True)
    category_id = fields.Many2one("arco.approval.category", string="Type", required=True, tracking=True)
    request_type = fields.Selection(related="category_id.request_type", store=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("done", "Executed"),
            ("rejected", "Rejected"),
            ("cancel", "Cancelled"),
        ],
        default="draft", tracking=True, copy=False, index=True,
    )
    requested_by = fields.Many2one("res.users", default=lambda self: self.env.user, required=True, tracking=True)
    employee_id = fields.Many2one(
        "hr.employee", compute="_compute_employee", store=True, readonly=False
    )
    department_id = fields.Many2one("hr.department", compute="_compute_employee", store=True, readonly=False)
    supervisor_user_id = fields.Many2one("res.users", string="Supervisor", compute="_compute_approvers", store=True)
    dept_head_user_id = fields.Many2one("res.users", string="Department Head", compute="_compute_approvers", store=True)
    supervisor_is_dept_head = fields.Boolean(compute="_compute_approvers", store=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id, required=True)
    amount = fields.Monetary(tracking=True)
    amount_company = fields.Monetary(
        "Amount (Company Currency)", compute="_compute_amount_company", store=True,
        currency_field="company_currency_id",
    )
    company_currency_id = fields.Many2one(related="company_id.currency_id", string="Company Currency")
    partner_id = fields.Many2one("res.partner", string="Vendor / Partner", tracking=True)
    date = fields.Date("Request Date", default=fields.Date.context_today, required=True)
    date_from = fields.Date("From")
    date_to = fields.Date("To")
    description = fields.Html("Details / Justification")
    executive_required = fields.Boolean(compute="_compute_executive_required", store=True)
    date_approved = fields.Datetime(readonly=True, copy=False)
    date_done = fields.Datetime("Executed On", readonly=True, copy=False)
    has_amount = fields.Selection(related="category_id.has_amount")
    has_partner = fields.Selection(related="category_id.has_partner")
    has_period = fields.Selection(related="category_id.has_period")

    @api.depends("requested_by")
    def _compute_employee(self):
        for rec in self:
            emp = rec.requested_by.employee_id
            rec.employee_id = emp
            rec.department_id = emp.department_id

    @api.depends("employee_id.parent_id.user_id", "department_id.manager_id.user_id", "requested_by")
    def _compute_approvers(self):
        for rec in self:
            sup = rec.employee_id.parent_id.user_id
            head = rec.department_id.manager_id.user_id
            rec.supervisor_user_id = sup if sup != rec.requested_by else False
            rec.dept_head_user_id = head if head != rec.requested_by else False
            # when the supervisor is also the department head the step is asked only once
            rec.supervisor_is_dept_head = bool(rec.supervisor_user_id and rec.supervisor_user_id == rec.dept_head_user_id)

    @api.depends("amount", "currency_id", "date")
    def _compute_amount_company(self):
        for rec in self:
            rec.amount_company = rec.currency_id._convert(
                rec.amount, rec.company_id.currency_id, rec.company_id, rec.date or fields.Date.today()
            ) if rec.currency_id else rec.amount

    @api.depends("category_id.executive_rule", "category_id.executive_threshold", "amount_company")
    def _compute_executive_required(self):
        for rec in self:
            rule = rec.category_id.executive_rule
            rec.executive_required = rule == "always" or (
                rule == "threshold" and rec.amount_company > rec.category_id.executive_threshold
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("arco.approval.request") or "New"
        return super().create(vals_list)

    # ----------------------------------------------------------------- flow
    def _check_submit(self):
        for rec in self:
            cat = rec.category_id
            if cat.has_amount == "required" and not rec.amount:
                raise UserError(_("%s: an amount is required.", cat.name))
            if cat.has_partner == "required" and not rec.partner_id:
                raise UserError(_("%s: select the vendor/partner.", cat.name))
            if cat.has_period == "required" and not (rec.date_from and rec.date_to):
                raise UserError(_("%s: a date range is required.", cat.name))
            if cat.requires_document and not rec.message_attachment_count:
                raise UserError(_("%s: attach the supporting document before submitting.", cat.name))

    def action_submit(self):
        self._check_submit()
        for rec in self:
            rec.state = "submitted"
            reviews = rec.request_validation()
            if not reviews:
                # nothing to review under the current matrix: approve straight away
                rec._arco_on_approved()
        return True

    def _validate_tier(self, tiers=False):
        res = super()._validate_tier(tiers)
        for rec in self.filtered(lambda r: r.state == "submitted" and r.validated):
            rec._arco_on_approved()
        return res

    def _rejected_tier(self, tiers=False):
        res = super()._rejected_tier(tiers)
        for rec in self.filtered(lambda r: r.state == "submitted"):
            rec.state = "rejected"
            rec._arco_notify_requester(_("Your request %s was rejected.", rec.name))
        return res

    def _arco_on_approved(self):
        for rec in self:
            rec.write({"state": "approved", "date_approved": fields.Datetime.now()})
            rec._arco_notify_requester(_("Your request %s has been approved.", rec.name))
            if rec.category_id.auto_execute:
                rec.action_execute()

    def _arco_notify_requester(self, body):
        self.ensure_one()
        self.message_post(
            body=body,
            partner_ids=self.requested_by.partner_id.ids,
            subtype_xmlid="mail.mt_comment",
        )

    def action_execute(self):
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("Only approved requests can be executed."))
            handler = getattr(rec, f"_execute_{rec.request_type}", None)
            if handler:
                handler()
            rec.write({"state": "done", "date_done": fields.Datetime.now()})
        return True

    def _execute_vendor_onboarding(self):
        if self.partner_id:
            self.partner_id.commercial_partner_id.sudo().write({"arco_vendor_approved": True, "supplier_rank": max(
                self.partner_id.commercial_partner_id.supplier_rank, 1)})
            self.message_post(body=_("%s marked as an approved vendor.", self.partner_id.display_name))

    def action_draft(self):
        self.restart_validation()
        self.write({"state": "draft"})

    def action_cancel(self):
        if any(r.state == "done" for r in self):
            raise UserError(_("Executed requests cannot be cancelled."))
        self.restart_validation()
        self.write({"state": "cancel"})


class TierDefinition(models.Model):
    _inherit = "tier.definition"

    @api.model
    def _get_tier_validation_model_names(self):
        res = super()._get_tier_validation_model_names()
        res.append("arco.approval.request")
        return res

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class ArcoProjectRequest(models.Model):
    _name = "arco.project.request"
    _description = "Project Request"
    _inherit = ["mail.thread", "mail.activity.mixin", "tier.validation"]
    _order = "id desc"
    _state_from = ["submitted"]
    _state_to = ["approved"]
    _cancel_state = "rejected"
    _tier_validation_manual_config = False

    name = fields.Char("Reference", default="New", readonly=True, copy=False)
    title = fields.Char("Project Name", required=True, tracking=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "In Approval"),
            ("approved", "Approved"),
            ("done", "Project Created"),
            ("rejected", "Rejected"),
            ("cancel", "Cancelled"),
        ],
        default="draft", tracking=True, copy=False, index=True,
    )
    company_id = fields.Many2one(
        "res.company", string="Business Unit", default=lambda self: self.env.company, required=True,
        help="Subsidiary / branch that will execute the project (AMEL, AMOS, AISL, AWS...)",
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    requested_by = fields.Many2one("res.users", default=lambda self: self.env.user, required=True, tracking=True)
    department_id = fields.Many2one("hr.department", default=lambda self: self.env.user.employee_id.department_id)
    partner_id = fields.Many2one("res.partner", string="Client", tracking=True)
    client_reference = fields.Char("Client PO / Contract Ref.")
    project_manager_id = fields.Many2one("res.users", string="Proposed Project Manager", tracking=True)
    date_start = fields.Date("Planned Start")
    date_end = fields.Date("Planned End")
    objective = fields.Html("Objectives & Scope")
    risk_notes = fields.Text("Key Risks / HSE Considerations")
    contract_value = fields.Monetary("Contract / Revenue Value", tracking=True)
    budget_line_ids = fields.One2many("arco.project.request.budget", "request_id", string="Cost Budget", copy=True)
    budget_total = fields.Monetary("Total Cost Budget", compute="_compute_totals", store=True)
    expected_margin = fields.Monetary(compute="_compute_totals", store=True)
    expected_margin_pct = fields.Float("Expected Margin %", compute="_compute_totals", store=True)
    resource_ids = fields.One2many("arco.project.resource", "request_id", string="Resource Plan", copy=True)
    project_id = fields.Many2one("project.project", readonly=True, copy=False)

    @api.depends("budget_line_ids.amount", "contract_value")
    def _compute_totals(self):
        for rec in self:
            total = sum(rec.budget_line_ids.mapped("amount"))
            rec.budget_total = total
            rec.expected_margin = rec.contract_value - total
            rec.expected_margin_pct = (rec.contract_value - total) / rec.contract_value * 100 if rec.contract_value else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("arco.project.request") or "New"
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            if not rec.budget_line_ids:
                raise UserError(_("Add the cost budget before submitting %s.", rec.name))
            rec.state = "submitted"
            rec.request_validation()
        return True

    def _validate_tier(self, tiers=False):
        res = super()._validate_tier(tiers)
        for rec in self.filtered(lambda r: r.state == "submitted" and r.validated):
            rec.state = "approved"
            rec.message_post(body=_("Project approved by PMO, Finance and Executive."),
                             partner_ids=rec.requested_by.partner_id.ids)
        return res

    def _rejected_tier(self, tiers=False):
        res = super()._rejected_tier(tiers)
        self.filtered(lambda r: r.state == "submitted").write({"state": "rejected"})
        return res

    def action_draft(self):
        self.restart_validation()
        self.write({"state": "draft"})

    def action_cancel(self):
        if any(r.state == "done" for r in self):
            raise UserError(_("The project already exists; archive it instead."))
        self.restart_validation()
        self.write({"state": "cancel"})

    def action_create_project(self):
        """Project Creation + Resource Assignment."""
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("%s must be approved first.", rec.name))
            project = self.env["project.project"].create({
                "name": rec.title,
                "partner_id": rec.partner_id.id,
                "company_id": rec.company_id.id,
                "user_id": rec.project_manager_id.id,
                "date_start": rec.date_start,
                "date": rec.date_end,
                "description": rec.objective,
                "arco_contract_value": rec.contract_value,
                "arco_request_id": rec.id,
            })
            if not project.account_id:
                project._create_analytic_account()
            project.arco_budget_line_ids = [Command.create({
                "category_id": line.category_id.id,
                "name": line.name,
                "planned_amount": line.amount,
                "sequence": line.sequence,
            }) for line in rec.budget_line_ids]
            rec.resource_ids.write({"project_id": project.id})
            users = rec.resource_ids.employee_id.user_id | rec.project_manager_id
            if users:
                project.message_subscribe(partner_ids=users.partner_id.ids)
            rec.write({"project_id": project.id, "state": "done"})
            rec.message_post(body=_("Project %s created.", project.display_name))
        return self.action_view_project()

    def action_view_project(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "project.project",
            "res_id": self.project_id.id,
            "view_mode": "form",
        }


class ArcoProjectRequestBudget(models.Model):
    _name = "arco.project.request.budget"
    _description = "Project Request Cost Budget"
    _order = "sequence, id"

    request_id = fields.Many2one("arco.project.request", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    category_id = fields.Many2one("arco.cost.category", required=True)
    name = fields.Char("Description")
    currency_id = fields.Many2one(related="request_id.currency_id")
    amount = fields.Monetary("Budget")


class ArcoProjectResource(models.Model):
    _name = "arco.project.resource"
    _description = "Project Resource Assignment"
    _order = "date_from, id"

    request_id = fields.Many2one("arco.project.request", ondelete="cascade", index=True)
    project_id = fields.Many2one("project.project", ondelete="cascade", index=True)
    employee_id = fields.Many2one("hr.employee", required=True)
    job_id = fields.Many2one(related="employee_id.job_id", string="Job Position")
    role = fields.Char("Project Role")
    planned_hours = fields.Float()
    date_from = fields.Date("From")
    date_to = fields.Date("To")


class ProjectProject(models.Model):
    _inherit = "project.project"

    arco_request_id = fields.Many2one("arco.project.request", string="Project Request", readonly=True, copy=False)
    arco_resource_ids = fields.One2many("arco.project.resource", "project_id", string="Resource Plan")


class TierDefinition(models.Model):
    _inherit = "tier.definition"

    @api.model
    def _get_tier_validation_model_names(self):
        res = super()._get_tier_validation_model_names()
        res.append("arco.project.request")
        return res

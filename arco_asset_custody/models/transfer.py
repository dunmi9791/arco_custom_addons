from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class ArcoAssetTransfer(models.Model):
    """Movement of fixed assets between custodians, departments, sites and cost centres."""

    _name = "arco.asset.transfer"
    _description = "Asset Transfer"
    _inherit = ["mail.thread", "mail.activity.mixin", "analytic.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Awaiting Approval"),
            ("approved", "Awaiting Receipt"),
            ("done", "Completed"),
            ("rejected", "Rejected"),
            ("cancel", "Cancelled"),
        ],
        default="draft", tracking=True, copy=False,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    date = fields.Date("Transfer Date", default=fields.Date.context_today, required=True, tracking=True)
    requested_by = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True)
    asset_ids = fields.Many2many(
        "account.asset", string="Assets", domain="[('state', 'in', ('open', 'close')), ('company_id', '=', company_id)]"
    )
    line_ids = fields.One2many("arco.asset.transfer.line", "transfer_id", string="Assets Moved", readonly=True)
    to_employee_id = fields.Many2one("hr.employee", string="New Custodian", tracking=True)
    to_department_id = fields.Many2one("hr.department", string="New Department", tracking=True)
    to_location_id = fields.Many2one("arco.asset.location", string="New Site / Location", tracking=True)
    change_cost_centre = fields.Boolean(
        "Change Cost Centre", help="Also move future depreciation to the analytic distribution below."
    )
    reason = fields.Text(required=True)
    approved_by = fields.Many2one("res.users", readonly=True, copy=False)
    received_by = fields.Many2one("res.users", readonly=True, copy=False)
    date_received = fields.Datetime(readonly=True, copy=False)
    receiver_signature = fields.Binary("Receiver Signature", copy=False, attachment=True)
    condition_on_receipt = fields.Selection(
        [("good", "Good"), ("fair", "Fair"), ("poor", "Poor"), ("damaged", "Damaged")], copy=False
    )

    @api.onchange("to_employee_id")
    def _onchange_to_employee_id(self):
        if self.to_employee_id.department_id:
            self.to_department_id = self.to_employee_id.department_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("arco.asset.transfer") or "New"
        return super().create(vals_list)

    def _snapshot_lines(self):
        for rec in self:
            rec.line_ids.unlink()
            rec.line_ids = [Command.create({
                "asset_id": asset.id,
                "from_employee_id": asset.arco_custodian_id.id,
                "from_department_id": asset.arco_department_id.id,
                "from_location_id": asset.arco_location_id.id,
                "from_analytic_distribution": asset.analytic_distribution,
            }) for asset in rec.asset_ids]

    def action_submit(self):
        for rec in self:
            if not rec.asset_ids:
                raise UserError(_("Select the assets to transfer."))
            if not (rec.to_employee_id or rec.to_department_id or rec.to_location_id or rec.change_cost_centre):
                raise UserError(_("Set at least one destination (custodian, department, site or cost centre)."))
            busy = self.search([
                ("id", "!=", rec.id), ("state", "in", ("submitted", "approved")),
                ("asset_ids", "in", rec.asset_ids.ids),
            ])
            if busy:
                raise UserError(_("An asset is already on open transfer %s.", busy[0].name))
            rec._snapshot_lines()
            rec.state = "submitted"
            group = self.env.ref("account.group_account_manager")
            for user in group.users[:5]:
                rec.activity_schedule(
                    "mail.mail_activity_data_todo", user_id=user.id,
                    summary=_("Approve asset transfer %s", rec.name),
                )
        return True

    def _check_approver(self):
        if not (self.env.user.has_group("account.group_account_manager")
                or self.env.user.has_group("arco_base.group_arco_finance_approver")):
            raise UserError(_("Only Finance / Asset Managers can approve asset transfers."))

    def action_approve(self):
        self._check_approver()
        for rec in self:
            rec.write({"state": "approved", "approved_by": self.env.user.id})
            rec.activity_ids.action_feedback(feedback=_("Approved"))
            receiver = rec.to_employee_id.user_id
            if receiver:
                rec.activity_schedule(
                    "mail.mail_activity_data_todo", user_id=receiver.id,
                    summary=_("Acknowledge receipt of assets (%s)", rec.name),
                )
        return True

    def action_reject(self):
        self._check_approver()
        self.activity_ids.unlink()
        self.write({"state": "rejected"})

    def action_receive(self):
        """Receiver acknowledges; custody moves and each asset logs the change."""
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("The transfer must be approved first."))
            receiver = rec.to_employee_id.user_id
            is_finance = self.env.user.has_group("account.group_account_manager")
            if receiver and receiver != self.env.user and not is_finance:
                raise UserError(_("Only %s (or Finance) can acknowledge this transfer.", receiver.name))
            for line in rec.line_ids:
                vals = {}
                if rec.to_employee_id:
                    vals["arco_custodian_id"] = rec.to_employee_id.id
                if rec.to_department_id:
                    vals["arco_department_id"] = rec.to_department_id.id
                if rec.to_location_id:
                    vals["arco_location_id"] = rec.to_location_id.id
                if rec.change_cost_centre:
                    vals["analytic_distribution"] = rec.analytic_distribution
                if rec.condition_on_receipt:
                    vals["arco_condition"] = {"damaged": "poor"}.get(rec.condition_on_receipt, rec.condition_on_receipt)
                line.asset_id.sudo().write(vals)
                line.asset_id.sudo().message_post(body=_(
                    "Transferred by %(ref)s: custodian %(src)s -> %(dst)s.",
                    ref=rec.name,
                    src=line.from_employee_id.name or "-",
                    dst=(rec.to_employee_id or line.from_employee_id).name or "-",
                ))
            rec.activity_ids.action_feedback(feedback=_("Received"))
            rec.write({"state": "done", "received_by": self.env.user.id, "date_received": fields.Datetime.now()})
        return True

    def action_cancel(self):
        if any(r.state == "done" for r in self):
            raise UserError(_("A completed transfer cannot be cancelled; raise a new transfer instead."))
        self.activity_ids.unlink()
        self.write({"state": "cancel"})

    def action_draft(self):
        self.write({"state": "draft"})


class ArcoAssetTransferLine(models.Model):
    _name = "arco.asset.transfer.line"
    _description = "Asset Transfer Line (custody history)"
    _order = "id desc"

    transfer_id = fields.Many2one("arco.asset.transfer", required=True, ondelete="cascade", index=True)
    asset_id = fields.Many2one("account.asset", required=True, index=True, ondelete="cascade")
    date = fields.Date(related="transfer_id.date", store=True)
    state = fields.Selection(related="transfer_id.state", store=True)
    from_employee_id = fields.Many2one("hr.employee", string="From Custodian")
    from_department_id = fields.Many2one("hr.department", string="From Department")
    from_location_id = fields.Many2one("arco.asset.location", string="From Site")
    from_analytic_distribution = fields.Json()
    to_employee_id = fields.Many2one(related="transfer_id.to_employee_id", string="To Custodian")
    to_department_id = fields.Many2one(related="transfer_id.to_department_id", string="To Department")
    to_location_id = fields.Many2one(related="transfer_id.to_location_id", string="To Site")
    reason = fields.Text(related="transfer_id.reason")

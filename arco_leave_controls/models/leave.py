from datetime import timedelta

from odoo import _, api, fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    arco_leave_reminder_days = fields.Integer(
        "Remind approvers after (days)", default=2,
        help="Pending time off requests older than this trigger a daily reminder to the approver.",
    )


class HrLeave(models.Model):
    _inherit = "hr.leave"

    arco_last_reminder = fields.Datetime("Last Reminder Sent", readonly=True, copy=False)
    arco_remaining_before = fields.Float(
        "Balance at Request (days)", readonly=True, copy=False,
        help="Remaining allocation for this type when the request was made.",
    )

    def _arco_hr_partners(self):
        self.ensure_one()
        users = self.holiday_status_id.responsible_ids
        if not users:
            users = self.env.ref("hr_holidays.group_hr_holidays_user").users.filtered(
                lambda u: self.employee_id.company_id in u.company_ids
            )
        return users.partner_id

    @api.model_create_multi
    def create(self, vals_list):
        leaves = super().create(vals_list)
        for leave in leaves:
            if leave.holiday_status_id.requires_allocation == "yes":
                data = leave.holiday_status_id.with_context(employee_id=leave.employee_id.id)
                leave.sudo().arco_remaining_before = data.virtual_remaining_leaves + leave.number_of_days
            partners = leave._arco_hr_partners()
            if partners and leave.state in ("confirm", "validate1"):
                leave.sudo().message_post(
                    body=_(
                        "New time off request: %(emp)s, %(type)s, %(start)s to %(end)s (%(days)s day(s)).",
                        emp=leave.employee_id.name, type=leave.holiday_status_id.name,
                        start=leave.request_date_from, end=leave.request_date_to, days=leave.number_of_days,
                    ),
                    partner_ids=partners.ids,
                    subtype_xmlid="mail.mt_note",
                )
        return leaves

    @api.model
    def _cron_arco_leave_reminders(self):
        now = fields.Datetime.now()
        for company in self.env["res.company"].search([]):
            limit = now - timedelta(days=company.arco_leave_reminder_days or 2)
            pending = self.search([
                ("employee_company_id", "=", company.id),
                ("state", "in", ("confirm", "validate1")),
                ("create_date", "<=", limit),
                "|", ("arco_last_reminder", "=", False), ("arco_last_reminder", "<=", now - timedelta(days=1)),
            ])
            for leave in pending:
                if leave.state == "confirm":
                    approvers = leave.employee_id.leave_manager_id.partner_id
                    step = _("manager approval")
                else:
                    approvers = leave._arco_hr_partners()
                    step = _("HR review")
                if not approvers:
                    continue
                leave.message_post(
                    body=_(
                        "Reminder: %(emp)s's time off request (%(start)s - %(end)s) is waiting for %(step)s since %(since)s.",
                        emp=leave.employee_id.name, start=leave.request_date_from, end=leave.request_date_to,
                        step=step, since=fields.Date.to_string(leave.create_date.date()),
                    ),
                    partner_ids=approvers.ids,
                    subtype_xmlid="mail.mt_comment",
                )
                leave.arco_last_reminder = now

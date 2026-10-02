from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ArcoPurchaseRequest(models.Model):
    _name = "arco.purchase.request"
    _description = "Purchase Requisition"
    _inherit = ["mail.thread", "mail.activity.mixin", "tier.validation"]
    _order = "id desc"
    # tier validation: submitted -> approved is gated by the ARCO authorization matrix
    _state_from = ["submitted"]
    _state_to = ["approved"]
    _cancel_state = "rejected"
    _tier_validation_manual_config = False

    name = fields.Char("Reference", default="New", copy=False, readonly=True, tracking=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("done", "Converted to RFQ/PO"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        tracking=True,
        copy=False,
        index=True,
    )
    requested_by = fields.Many2one(
        "res.users", default=lambda self: self.env.user, required=True, tracking=True
    )
    department_id = fields.Many2one(
        "hr.department",
        default=lambda self: self.env.user.employee_id.department_id,
        tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date_request = fields.Date("Request Date", default=fields.Date.context_today, required=True)
    date_required = fields.Date("Required By", tracking=True)
    priority = fields.Selection(
        [("0", "Normal"), ("1", "Urgent"), ("2", "Critical (Ops down)")], default="0", tracking=True
    )
    project_id = fields.Many2one("project.project", tracking=True)
    picking_type_id = fields.Many2one(
        "stock.picking.type",
        string="Deliver To",
        domain="[('code', '=', 'incoming'), ('company_id', '=', company_id)]",
    )
    justification = fields.Text(required=False)
    line_ids = fields.One2many("arco.purchase.request.line", "request_id", copy=True)
    amount_total = fields.Monetary("Estimated Total", compute="_compute_amount", store=True)
    purchase_ids = fields.Many2many("purchase.order", compute="_compute_purchase_ids")
    purchase_count = fields.Integer(compute="_compute_purchase_ids")
    reject_reason = fields.Text(readonly=True, copy=False)
    dept_manager_user_id = fields.Many2one(
        "res.users",
        string="Approving Manager",
        compute="_compute_dept_manager_user_id",
        store=True,
        help="Department manager of the requester (or the requester's line manager). "
        "Used by the first tier of the authorization matrix.",
    )

    @api.depends("department_id.manager_id.user_id", "requested_by")
    def _compute_dept_manager_user_id(self):
        for rec in self:
            user = rec.department_id.manager_id.user_id
            if not user or user == rec.requested_by:
                employee = rec.requested_by.employee_id
                user = employee.parent_id.user_id or user
            rec.dept_manager_user_id = user if user != rec.requested_by else False

    @api.depends("line_ids.subtotal")
    def _compute_amount(self):
        for rec in self:
            rec.amount_total = sum(rec.line_ids.mapped("subtotal"))

    def _compute_purchase_ids(self):
        for rec in self:
            pos = rec.line_ids.mapped("purchase_line_ids.order_id")
            rec.purchase_ids = pos
            rec.purchase_count = len(pos)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("arco.purchase.request") or "New"
        return super().create(vals_list)

    # ---------------------------------------------------------------- workflow
    def action_submit(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_("Add at least one line before submitting %s.", rec.name))
            rec.state = "submitted"
            rec.request_validation()
        return True

    def action_approve(self):
        # tier.validation blocks this write until every required reviewer has approved
        self.write({"state": "approved"})
        return True

    def action_reject(self):
        self.write({"state": "rejected"})
        return True

    def action_cancel(self):
        if any(r.state == "done" for r in self):
            raise UserError(_("A converted requisition cannot be cancelled; cancel the POs instead."))
        self.restart_validation()
        self.write({"state": "cancel"})

    def action_draft(self):
        self.restart_validation()
        self.write({"state": "draft", "reject_reason": False})

    def _validate_tier(self, tiers=False):
        res = super()._validate_tier(tiers)
        for rec in self.filtered(lambda r: r.state == "submitted" and r.validated):
            rec.action_approve()
        return res

    def _rejected_tier(self, tiers=False):
        res = super()._rejected_tier(tiers)
        self.filtered(lambda r: r.state == "submitted").write({"state": "rejected"})
        return res

    # ------------------------------------------------------------ conversion
    def _prepare_po_vals(self, vendor):
        self.ensure_one()
        vals = {
            "partner_id": vendor.id,
            "company_id": self.company_id.id,
            "origin": self.name,
            "date_planned": self.date_required or fields.Datetime.now(),
        }
        if self.picking_type_id:
            vals["picking_type_id"] = self.picking_type_id.id
        return vals

    def action_create_rfq(self):
        PO = self.env["purchase.order"]
        created = PO
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("%s must be approved before creating RFQs.", rec.name))
            by_vendor = defaultdict(lambda: self.env["arco.purchase.request.line"])
            for line in rec.line_ids.filtered(lambda l: not l.purchase_line_ids):
                vendor = line.vendor_id or line.product_id._select_seller(
                    quantity=line.product_qty, uom_id=line.product_uom_id
                ).partner_id
                if not vendor:
                    raise UserError(
                        _("Set a suggested vendor on line '%s' (no vendor pricelist found).", line.name)
                    )
                by_vendor[vendor] |= line
            for vendor, lines in by_vendor.items():
                po = PO.create(rec._prepare_po_vals(vendor))
                for line in lines:
                    self.env["purchase.order.line"].create(line._prepare_po_line_vals(po))
                created |= po
            rec.state = "done"
        action = self.env["ir.actions.act_window"]._for_xml_id("purchase.purchase_rfq")
        action["domain"] = [("id", "in", created.ids)]
        return action

    def action_view_purchase(self):
        action = self.env["ir.actions.act_window"]._for_xml_id("purchase.purchase_rfq")
        action["domain"] = [("id", "in", self.purchase_ids.ids)]
        return action


class ArcoPurchaseRequestLine(models.Model):
    _name = "arco.purchase.request.line"
    _description = "Purchase Requisition Line"
    _inherit = ["analytic.mixin"]

    request_id = fields.Many2one("arco.purchase.request", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="request_id.company_id", store=True)
    currency_id = fields.Many2one(related="request_id.currency_id")
    state = fields.Selection(related="request_id.state", store=True)
    product_id = fields.Many2one("product.product", domain="[('purchase_ok', '=', True)]", required=True)
    name = fields.Char("Description", required=True)
    product_qty = fields.Float("Quantity", default=1.0, digits="Product Unit of Measure", required=True)
    product_uom_id = fields.Many2one("uom.uom", string="UoM", required=True)
    estimated_unit_cost = fields.Monetary("Est. Unit Cost")
    subtotal = fields.Monetary(compute="_compute_subtotal", store=True)
    vendor_id = fields.Many2one("res.partner", string="Suggested Vendor", domain="[('supplier_rank', '>', 0)]")
    purchase_line_ids = fields.One2many("purchase.order.line", "arco_request_line_id", readonly=True)
    qty_ordered = fields.Float(compute="_compute_qty_ordered", digits="Product Unit of Measure")

    @api.depends("product_qty", "estimated_unit_cost")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.product_qty * line.estimated_unit_cost

    def _compute_qty_ordered(self):
        for line in self:
            line.qty_ordered = sum(
                pl.product_uom._compute_quantity(pl.product_qty, line.product_uom_id)
                for pl in line.purchase_line_ids.filtered(lambda p: p.state != "cancel")
            )

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.display_name
            self.product_uom_id = self.product_id.uom_po_id or self.product_id.uom_id
            self.estimated_unit_cost = self.product_id.standard_price
            seller = self.product_id.seller_ids[:1]
            if seller and not self.vendor_id:
                self.vendor_id = seller.partner_id
            project = self.request_id.project_id
            if project.account_id and not self.analytic_distribution:
                self.analytic_distribution = {str(project.account_id.id): 100}

    def _prepare_po_line_vals(self, po):
        self.ensure_one()
        return {
            "order_id": po.id,
            "product_id": self.product_id.id,
            "name": self.name,
            "product_qty": self.product_qty,
            "product_uom": self.product_uom_id.id,
            "price_unit": self.estimated_unit_cost,
            "date_planned": self.request_id.date_required or fields.Datetime.now(),
            "analytic_distribution": self.analytic_distribution,
            "arco_request_line_id": self.id,
        }

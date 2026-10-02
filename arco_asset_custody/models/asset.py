from odoo import api, fields, models


class ArcoAssetLocation(models.Model):
    _name = "arco.asset.location"
    _description = "Asset Site / Location"
    _parent_store = True
    _rec_name = "complete_name"
    _order = "complete_name"

    name = fields.Char(required=True)
    complete_name = fields.Char(compute="_compute_complete_name", store=True, recursive=True)
    parent_id = fields.Many2one("arco.asset.location", index=True, ondelete="restrict")
    parent_path = fields.Char(index=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    address = fields.Char()
    active = fields.Boolean(default=True)

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        for loc in self:
            loc.complete_name = (
                f"{loc.parent_id.complete_name} / {loc.name}" if loc.parent_id else loc.name
            )


class AccountAsset(models.Model):
    _inherit = "account.asset"

    arco_tag_number = fields.Char("Tag / Barcode No.", tracking=True, copy=False)
    arco_serial_number = fields.Char("Serial No.", tracking=True, copy=False)
    arco_custodian_id = fields.Many2one("hr.employee", string="Custodian", tracking=True, index=True)
    arco_department_id = fields.Many2one("hr.department", string="Department", tracking=True)
    arco_location_id = fields.Many2one("arco.asset.location", string="Site / Location", tracking=True)
    arco_condition = fields.Selection(
        [("new", "New"), ("good", "Good"), ("fair", "Fair"), ("poor", "Poor"), ("unserviceable", "Unserviceable")],
        string="Condition", default="good", tracking=True,
    )
    arco_transfer_line_ids = fields.One2many(
        "arco.asset.transfer.line", "asset_id", string="Custody History",
        domain=[("transfer_id.state", "=", "done")],
    )
    arco_transfer_count = fields.Integer(compute="_compute_arco_transfer_count")

    _sql_constraints = [
        ("arco_tag_unique", "unique(arco_tag_number, company_id)", "Asset tag numbers must be unique."),
    ]

    def _compute_arco_transfer_count(self):
        data = dict(self.env["arco.asset.transfer.line"]._read_group(
            [("asset_id", "in", self.ids)], ["asset_id"], ["__count"]
        ))
        for asset in self:
            asset.arco_transfer_count = data.get(asset, 0)

    @api.onchange("arco_custodian_id")
    def _onchange_arco_custodian_id(self):
        if self.arco_custodian_id.department_id:
            self.arco_department_id = self.arco_custodian_id.department_id

    def action_arco_transfer(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Asset Transfer",
            "res_model": "arco.asset.transfer",
            "view_mode": "form",
            "context": {"default_asset_ids": self.ids},
        }

    def action_arco_view_transfers(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Transfers",
            "res_model": "arco.asset.transfer",
            "view_mode": "list,form",
            "domain": [("line_ids.asset_id", "=", self.id)],
        }

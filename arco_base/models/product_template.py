from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    arco_equipment_class = fields.Selection(
        [
            ("consumable", "Consumable"),
            ("spare", "Critical Spare"),
            ("ppe", "PPE / Safety"),
            ("chemical", "Chemical / Hazardous"),
            ("rotating", "Rotating Equipment"),
            ("static", "Static Equipment"),
            ("service", "Service"),
        ],
        string="Equipment Class",
    )
    arco_hs_code = fields.Char("HS Code")
    arco_is_critical = fields.Boolean("Critical Item", help="Stock-out affects field operations")

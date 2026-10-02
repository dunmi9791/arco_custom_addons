from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    arco_tin = fields.Char("TIN", tracking=True, help="FIRS/NRS Tax Identification Number")
    arco_rc_number = fields.Char("RC Number", tracking=True, help="CAC registration number")
    arco_vendor_category = fields.Selection(
        [
            ("oem", "OEM / Manufacturer"),
            ("distributor", "Distributor / Local Supplier"),
            ("service", "Service Contractor"),
            ("logistics", "Marine & Logistics"),
            ("professional", "Professional / Consultancy"),
            ("government", "Government / Regulator"),
        ],
        string="Vendor Category",
        tracking=True,
    )
    arco_nipex_number = fields.Char("NipeX / NUPRC JQS No.", tracking=True)
    arco_ncdmb_registered = fields.Boolean("NCDMB (NOGICD) Registered", tracking=True)
    arco_ncdmb_expiry = fields.Date("NCDMB Certificate Expiry", tracking=True)
    arco_vendor_approved = fields.Boolean(
        "Approved Vendor", tracking=True, help="Vendor has passed ARCO onboarding/prequalification"
    )
    arco_compliance_expired = fields.Boolean(compute="_compute_arco_compliance_expired")

    @api.depends("arco_ncdmb_expiry")
    def _compute_arco_compliance_expired(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.arco_compliance_expired = bool(rec.arco_ncdmb_expiry and rec.arco_ncdmb_expiry < today)

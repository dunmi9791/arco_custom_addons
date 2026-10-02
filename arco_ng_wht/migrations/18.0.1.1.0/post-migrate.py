"""Flag existing WHT category taxes so WHT and NCD deductions are reported separately."""


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    env["arco.wht.category"].with_context(active_test=False).search([])._arco_flag_taxes()
    env["account.move"].search([("move_type", "!=", "entry")])._compute_arco_wht_amount()

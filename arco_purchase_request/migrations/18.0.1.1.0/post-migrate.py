"""Archive the placeholder PR tiers (N5m/N20m); the SMERP workflow tiers are created by the upgrade."""


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid in ("tier_pr_l1", "tier_pr_l2", "tier_pr_l3"):
        rec = env.ref(f"arco_purchase_request.{xmlid}", raise_if_not_found=False)
        if rec:
            rec.active = False
    env["arco.purchase.request"].search([])._compute_dept_manager_user_id()

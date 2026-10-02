"""Switch ARGO from the placeholder matrix (N1m/N5m/N20m) to the SMERP matrix.

tier_definitions.xml is noupdate, so the new records are created on upgrade but the
old ones would linger. Archive them and align the vendor-bill tier with company currency.
"""


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid in ("tier_po_l1", "tier_po_l2", "tier_po_l3"):
        rec = env.ref(f"arco_approval_matrix.{xmlid}", raise_if_not_found=False)
        if rec:
            rec.active = False
    bill = env.ref("arco_approval_matrix.tier_bill_l1", raise_if_not_found=False)
    if bill:
        bill.write({
            "name": "Vendor Bill - Finance Manager (above N5m)",
            "definition_domain": '[("move_type", "=", "in_invoice"), ("arco_amount_company", ">", 5000000)]',
        })

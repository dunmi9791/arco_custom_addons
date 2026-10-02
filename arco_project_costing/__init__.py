from . import models


def post_init_hook(env):
    """Create default cost categories and map them to the Nigerian chart of accounts by code."""
    Cat = env["arco.cost.category"]
    Account = env["account.account"]
    mapping = [
        ("Materials & Spares", "MAT", ["500000", "611000"]),
        ("Labour & Manpower", "LAB", ["630000"]),
        ("Subcontract & Equipment Hire", "SUB", ["510200"]),
        ("Logistics & Marine", "LOG", []),
        ("Overheads & Other", "OTH", ["600000", "612000"]),
    ]
    for seq, (name, code, codes) in enumerate(mapping, start=1):
        if Cat.search([("code", "=", code)], limit=1):
            continue
        accounts = Account.search([("code", "in", codes)]) if codes else Account
        Cat.create({"name": name, "code": code, "sequence": seq, "account_ids": [(6, 0, accounts.ids)]})

from . import models

ITEMS = [
    ("DIRECT", "Direct Costs (Cost of Sales)", ["expense_direct_cost"]),
    ("OPEX", "Operating Expenses", ["expense"]),
    ("DEPR", "Depreciation", ["expense_depreciation"]),
    ("CAPEX", "Capital Expenditure", ["asset_fixed"]),
]


def post_init_hook(env):
    """Seed budget items from the chart of accounts (one per cost nature)."""
    Item = env["arco.budget.item"]
    for company in env["res.company"].search([("parent_id", "=", False)]):
        for seq, (code, name, types) in enumerate(ITEMS, start=1):
            if Item.search_count([("code", "=", code), ("company_id", "=", company.id)]):
                continue
            accounts = env["account.account"].search(
                [("account_type", "in", types), ("company_ids", "in", company.id)]
            )
            if accounts:
                Item.create({
                    "name": name, "code": code, "sequence": seq * 10,
                    "company_id": company.id, "account_ids": [(6, 0, accounts.ids)],
                })

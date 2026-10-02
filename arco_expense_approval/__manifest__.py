{
    "name": "ARCO Expense Claim Approval",
    "version": "18.0.1.0.0",
    "summary": "SMERP expense workflow: receipt mandatory on submit, Line Manager -> Finance Verification "
    "(receipts + budget) -> Finance Approval, then posting and reimbursement",
    "author": "Secteur Network Solutions",
    "category": "ARCO",
    "license": "LGPL-3",
    "depends": ["arco_base", "arco_budget_control", "base_tier_validation", "hr_expense"],
    "data": [
        "security/expense_security.xml",
        "data/tier_definitions.xml",
        "views/expense_views.xml",
    ],
    "installable": True,
}

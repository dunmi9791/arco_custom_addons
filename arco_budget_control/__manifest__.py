{
    "name": "ARCO Budget Control",
    "version": "18.0.1.0.0",
    "summary": "Annual budgets by cost centre / project and budget item, budget availability check on "
    "requisitions and POs (warn or block), budget vs actual report, budget transfers through Approvals",
    "author": "Secteur Network Solutions",
    "category": "ARCO",
    "license": "LGPL-3",
    "depends": ["arco_base", "arco_approvals", "arco_purchase_request", "account", "analytic", "purchase"],
    "data": [
        "security/ir.model.access.csv",
        "security/budget_security.xml",
        "data/approval_category.xml",
        "views/budget_views.xml",
        "views/approval_views.xml",
        "report/budget_report.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
}

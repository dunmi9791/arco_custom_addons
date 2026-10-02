{
    "name": "ARCO Project & Job Costing",
    "version": "18.0.1.0.0",
    "summary": "Project budgets by cost category, actuals from analytic accounting, PO commitments, revenue and margin",
    "author": "Secteur Network Solutions",
    "category": "ARCO",
    "license": "LGPL-3",
    "depends": ["arco_base", "project_account", "purchase", "account", "analytic"],
    "data": [
        "security/ir.model.access.csv",
        "views/project_costing_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
}

{
    "name": "ARCO Project Requests",
    "version": "18.0.1.0.0",
    "summary": "SMERP project approval: Business Unit request -> PMO Review -> Budget Approval -> "
    "Executive Approval -> project created with analytic account, cost budget and resource plan",
    "author": "Secteur Network Solutions",
    "category": "ARCO",
    "license": "LGPL-3",
    "depends": ["arco_base", "arco_project_costing", "base_tier_validation", "hr"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/tier_definitions.xml",
        "views/project_request_views.xml",
    ],
    "installable": True,
}

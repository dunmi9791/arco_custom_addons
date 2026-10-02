{
    "name": "ARCO Purchase Requisition",
    "version": "18.0.1.1.0",
    "summary": "Digital Purchase Requisitions (PR) with cost centre/project coding, multi-level approval and PR -> RFQ/PO conversion",
    "author": "Secteur Network Solutions",
    "category": "ARCO",
    "license": "LGPL-3",
    "depends": ["arco_base", "arco_approval_matrix", "base_tier_validation", "purchase_stock", "project", "hr", "analytic"],
    "data": [
        "security/ir.model.access.csv",
        "security/pr_security.xml",
        "data/sequence.xml",
        "data/tier_definitions.xml",
        "views/purchase_request_views.xml",
        "views/purchase_order_views.xml",
    ],
    "installable": True,
    "application": True,
}

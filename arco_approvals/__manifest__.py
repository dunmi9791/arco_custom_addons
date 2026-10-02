{
    "name": "ARCO Approvals",
    "version": "18.0.1.0.0",
    "summary": "Generic SMERP approval requests (CapEx, spending, vendor onboarding, budget transfers...) "
    "with Supervisor -> Department Head -> Finance -> Executive flow and auto notification",
    "author": "Secteur Network Solutions",
    "category": "ARCO",
    "license": "LGPL-3",
    "depends": ["arco_base", "base_tier_validation", "hr", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "security/approval_security.xml",
        "data/sequence.xml",
        "data/approval_categories.xml",
        "data/tier_definitions.xml",
        "views/approval_views.xml",
    ],
    "application": True,
    "installable": True,
}

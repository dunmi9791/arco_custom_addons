{
    "name": "ARCO Vendor Contracts",
    "version": "18.0.1.0.0",
    "summary": "Vendor contract approval (Procurement -> Legal -> Finance -> Executive), electronic "
    "signature by ARCO and the vendor (portal), contract repository with expiry alerts",
    "author": "Secteur Network Solutions",
    "category": "ARCO",
    "license": "LGPL-3",
    "depends": ["arco_base", "base_tier_validation", "purchase", "project", "portal"],
    "data": [
        "security/ir.model.access.csv",
        "security/contract_security.xml",
        "data/sequence.xml",
        "data/tier_definitions.xml",
        "data/mail_template.xml",
        "data/cron.xml",
        "views/contract_views.xml",
        "views/portal_templates.xml",
        "report/contract_report.xml",
    ],
    "installable": True,
}

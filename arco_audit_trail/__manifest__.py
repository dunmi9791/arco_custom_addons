{
    "name": "ARCO Audit Trail",
    "version": "18.0.1.0.0",
    "summary": "Field-level audit log (who, when, old -> new) on financial and master-data records",
    "author": "Secteur Network Solutions",
    "category": "ARCO",
    "license": "LGPL-3",
    "depends": ["arco_base", "account", "purchase"],
    "data": [
        "security/ir.model.access.csv",
        "data/audit_rules.xml",
        "views/audit_views.xml",
    ],
    "installable": True,
}

{
    "name": "ARCO Fixed Asset Custody & Transfers",
    "version": "18.0.1.0.0",
    "summary": "Fixed asset register with custodian, department, site and tag; approved asset transfers "
    "between users/departments/sites/cost centres with receiver acknowledgement and custody history",
    "author": "Secteur Network Solutions",
    "category": "ARCO",
    "license": "LGPL-3",
    "depends": ["arco_base", "account_asset_management", "hr"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/asset_views.xml",
        "views/transfer_views.xml",
        "report/asset_register_report.xml",
    ],
    "installable": True,
}

{
    "name": "ARCO Nigeria Withholding Tax",
    "version": "18.0.1.1.0",
    "summary": "WHT categories per vendor/customer, automatic WHT on bills, WHT schedule for NRS/SIRS filing and WHT credit-note tracking",
    "author": "Secteur Network Solutions",
    "category": "ARCO",
    "license": "LGPL-3",
    "depends": ["arco_base", "account"],
    "data": [
        "security/ir.model.access.csv",
        "views/wht_views.xml",
    ],
    "installable": True,
}

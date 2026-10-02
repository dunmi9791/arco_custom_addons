{
    "name": "ARCO Approval & Authorization Matrix",
    "version": "18.0.1.1.0",
    "summary": "SMERP authorization matrix (N500k / N5m / N20m bands) on Purchase Orders and Vendor Bills, company-currency based (OCA tier validation)",
    "author": "Secteur Network Solutions",
    "category": "ARCO",
    "license": "LGPL-3",
    "depends": ["arco_base", "base_tier_validation", "purchase", "account"],
    "data": [
        "data/tier_definitions.xml",
    ],
    "installable": True,
}

{
    "name": "ARCO Sales Order Approval",
    "version": "18.0.1.0.0",
    "summary": "SMERP order-to-cash: discount approval matrix (0-5% Sales Executive, 5-15% Sales Manager, "
    ">15% Commercial Director), inventory availability check and automatic invoice on confirmation",
    "author": "Secteur Network Solutions",
    "category": "ARCO",
    "license": "LGPL-3",
    "depends": ["arco_base", "base_tier_validation", "sale_stock"],
    "data": [
        "data/tier_definitions.xml",
        "views/sale_views.xml",
    ],
    "installable": True,
}

{
    "name": "ARCO Base",
    "version": "18.0.1.1.0",
    "summary": "ARCO Group foundation: role groups, compliance fields for vendors/customers and products",
    "author": "Secteur Network Solutions",
    "category": "ARCO",
    "license": "LGPL-3",
    "depends": ["base", "mail", "account", "purchase", "stock", "project", "hr"],
    "data": [
        "security/arco_security.xml",
        "views/res_partner_views.xml",
        "views/product_views.xml",
    ],
    "installable": True,
    "application": False,
}

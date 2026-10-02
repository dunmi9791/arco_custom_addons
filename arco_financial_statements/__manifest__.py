{
    "name": "ARCO Financial Statements",
    "version": "18.0.1.0.0",
    "summary": "Profit & Loss, Balance Sheet and Cash Flow Statement (indirect method) for Odoo CE, "
    "with comparatives, branch filter, PDF/HTML output and monthly P&L emailed to management",
    "author": "Secteur Network Solutions",
    "category": "ARCO",
    "license": "LGPL-3",
    "depends": ["arco_base", "account"],
    "data": [
        "security/ir.model.access.csv",
        "report/financial_statement_report.xml",
        "wizard/financial_statement_wizard_views.xml",
        "views/res_config_settings_views.xml",
        "data/cron.xml",
        "data/mail_template.xml",
    ],
    "installable": True,
}

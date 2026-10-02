{
    "name": "ARCO Payment Vouchers & Payment Runs",
    "version": "18.0.1.0.0",
    "summary": "Vendor payment approval: payment vouchers/batches through the authorization matrix, "
    "payment creation, bank upload file (NIBSS NIP bulk CSV) and remittance advice",
    "author": "Secteur Network Solutions",
    "category": "ARCO",
    "license": "LGPL-3",
    "depends": ["arco_base", "base_tier_validation", "account"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/tier_definitions.xml",
        "data/mail_template.xml",
        "report/payment_voucher_report.xml",
        "views/payment_run_views.xml",
    ],
    "installable": True,
}

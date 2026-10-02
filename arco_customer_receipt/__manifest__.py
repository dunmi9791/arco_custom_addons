{
    "name": "ARCO Customer Receipts (Receipt Application)",
    "version": "18.0.1.0.0",
    "summary": "Customer receipt voucher: one bank receipt applied across several invoices "
    "(FIFO or manual), partial allocation, WHT/NCD deducted at receipt, unapplied cash on account",
    "author": "Secteur Network Solutions",
    "category": "ARCO",
    "license": "LGPL-3",
    "depends": ["arco_base", "account"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/customer_receipt_views.xml",
        "report/receipt_report.xml",
    ],
    "installable": True,
}

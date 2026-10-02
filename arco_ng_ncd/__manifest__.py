{
    "name": "ARCO Nigeria NCD Levy (NCDF 1%)",
    "version": "18.0.1.0.0",
    "summary": "Nigerian Content Development levy: 1% NCDF deduction on upstream contracts, posting on "
    "invoices and bills, NCD levy register, remittance to NCDMB and schedule report",
    "description": """
NOGICD Act 2010 s.104: 1% of every contract awarded in the upstream oil & gas sector is deducted
at source and paid to the Nigerian Content Development Fund (NCDF).

* Customer side: operators (SPDC, NLNG, Seplat...) deduct 1% from ARCO invoices -> NCD levy expense.
* Vendor side: ARCO deducts 1% from its subcontractors on upstream work -> NCDF payable.
* Automatic application on posting for partners flagged "NCD applicable", or manual "Apply NCD".
* NCD Levy Register (payable and suffered), pivot by month/partner.
* NCD Remittance: collect unremitted deductions for a period, post the payment to NCDMB, keep the
  NCDMB receipt reference and print the NCD schedule.
""",
    "author": "Secteur Network Solutions",
    "category": "ARCO",
    "license": "LGPL-3",
    "depends": ["arco_base", "arco_ng_wht", "account"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/ncd_views.xml",
        "report/ncd_schedule_report.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
}

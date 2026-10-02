# SMERP (Odoo 18 CE) - demo coverage for "Some of what SMERP can Demonstrate"

Secteur Network Solutions, 30 Sep 2026. All modules are Odoo 18.0 Community, LGPL-3, `arco_` prefix.

## Install / upgrade on ARGO

OCA modules needed (already in ARGO): `base_tier_validation`, `account_asset_management`
(+ `report_xlsx`, `report_xlsx_helper`).

```bash
# upgrade the modules that changed (migration scripts archive the old N1m/N5m/N20m tiers)
odoo -d argo -u arco_base,arco_approval_matrix,arco_purchase_request,arco_ng_wht --stop-after-init
# install the new ones
odoo -d argo -i arco_payment_run,arco_ng_ncd,arco_customer_receipt,arco_budget_control,\
arco_asset_custody,arco_financial_statements,arco_approvals,arco_expense_approval,\
arco_leave_controls,arco_sale_approval,arco_vendor_contract,arco_project_request --stop-after-init
```

After install, assign the new ARCO roles (Settings > Users > ARCO Roles): Finance Director,
Commercial Director, Legal Reviewer, PMO. "Finance Approver" is now labelled Finance Manager and
"Managing Director" is Executive Management / MD.

## Finance evaluation items

| # | Demo item | Where | Module |
|---|-----------|-------|--------|
| 1 | Sales invoice creation | Accounting > Customers > Invoices (or auto from SO) | standard + `arco_sale_approval` |
| 2 | VAT configuration | Accounting > Configuration > Taxes (l10n_ng 7.5%) | standard |
| 3 | WHT deduction | Vendor/customer WHT category; auto on bill posting; Reporting > Withholding Tax | `arco_ng_wht` |
| 4 | NCD posting and reporting | Partner "NCD Levy Applicable"; NCD tab on invoice/bill; Reporting > NCD Levy (NCDF) > registers, remittance, NCD schedule PDF | `arco_ng_ncd` (new) |
| 5 | Customer receipt application | Accounting > Customers > Customer Receipts: one receipt over many invoices, FIFO or manual, partial, WHT/NCD deducted at receipt, unapplied on account, Official Receipt PDF | `arco_customer_receipt` (new) |
| 6 | AR aging | Accounting > Reporting > Aged Partner Balance | OCA `account_financial_report` |
| 7 | Budget by cost centre | Accounting > Budgets > Budgets (cost centre/project x budget item) | `arco_budget_control` (new) |
| 8 | Budget vs actual | Accounting > Budgets > Budget vs Actual (actual, committed, available, used %) + PDF | `arco_budget_control` |
| 9 | Fixed asset register | Accounting > Assets (custodian, site, tag columns) + "Fixed Asset Register" PDF | OCA + `arco_asset_custody` (new) |
| 10 | Depreciation run | Accounting > Assets > Compute Assets | OCA `account_asset_management` |
| 11 | Asset transfer between users | Asset > Transfer, or Accounting > Assets > Asset Transfers: submit > Finance approve > receiver acknowledges (signature) > custody history | `arco_asset_custody` |
| 12 | Asset disposal | Asset > Remove (sale/scrap, gain/loss entry) | OCA `account_asset_management` |
| 13 | Full audit trail | Accounting > Reporting > Audit Trail + approval history on every document | `arco_audit_trail` |
| 14 | P&L, Balance Sheet, Cash Flow | Accounting > Reporting > Financial Statements (comparatives, branch filter, PDF/screen). Monthly P&L email to management (Settings > Accounting) | `arco_financial_statements` (new) |

## Approval workflows

Every flow uses the OCA tier engine: Validate / Reject buttons and a review panel appear on the
form, reviewers are notified in the chatter, steps run in sequence. Thresholds and approvers are
editable in Settings > Technical > Tier Definitions (company currency, NGN).

| # | Process | Flow in SMERP | Module |
|---|---------|---------------|--------|
| 1 | Purchase requisition to payment | PR > Department Manager > Procurement Review > Finance (N500,001-5m Finance Manager, 5m-20m Finance Director, >20m Executive) > RFQ/PO > receipt > bill > **Payment Voucher** (Finance Manager; >5m Finance Director; >20m Executive) > payments + bank upload CSV + remittance advice. Direct POs follow the same matrix; POs from an approved PR (within 10%) skip it. Bills can only be paid from an approved voucher (setting). | `arco_purchase_request`, `arco_approval_matrix`, `arco_payment_run` (new), `arco_budget_control` |
| 2 | Employee expense reimbursement | Receipt mandatory > Line Manager > Finance Verification (sees receipts + live budget check) > Finance Approval > post > pay | `arco_expense_approval` (new) |
| 3 | Leave request | Balance + overlap checks (standard) > Manager > HR review > calendar. HR notified on submission, daily reminders to approvers after N days | `arco_leave_controls` (new) |
| 4 | Sales order approval | Discount 0-5% none, 5-15% Sales Manager, >15% Commercial Director; stock availability warn/block; invoice auto-created on confirmation, then delivery | `arco_sale_approval` (new) |
| 5 | Vendor contract approval | Procurement > Legal > Finance > Executive > e-signature (MD in backend, vendor on portal link) > Contract Repository with expiry alerts | `arco_vendor_contract` (new) |
| 6 | Project approval | Request > PMO > Budget (Finance) > Executive > project created with analytic account, cost budget and resource plan | `arco_project_request` (new) |
| 7 | Generic approvals | Approvals app: Supervisor > Department Head > Finance > Executive (per type). Types shipped: CapEx, Spending, Vendor Onboarding (approves the vendor), Budget Transfer (moves budget), General. Requester notified automatically | `arco_approvals` (new) |

## Tested

Installed on a clean Odoo 18 CE + l10n_ng database and upgraded from the previous ARGO scaffolds.
86 scripted checks passed, covering every flow above (qa/ folder): tier sequences and thresholds,
blocking rules, WHT 5% + NCD 1% on a N1m bill (N1,015,000 net payable incl. VAT), NCD remittance,
receipt allocation with partial and deducted invoices, voucher > payment > bank file, budget block/warn
and transfer, Balance Sheet balancing and Cash Flow reconciling to bank, asset transfer, expense,
leave, SO discount/auto-invoice, contract signature, project creation. All PDFs render.

## Open points

- Thresholds follow the demo document. Load the signed Approval & Authorization Matrix when available.
- Confirm the NCD scope with ARCO Finance: which customers/contracts are upstream, and whether
  subcontractor deductions apply.
- Vendor e-signature uses the Odoo portal (vendor gets an emailed link). Outgoing mail must be configured.
- Budget engine is native (not mis_builder_budget), so the budget decision in the plan is closed.
- BI dashboards (arco_dashboards) are still planned.

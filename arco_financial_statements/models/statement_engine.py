"""Builds P&L, Balance Sheet and Cash Flow data from posted journal items, grouped by
account type (Odoo 18 account_type), so it works on any chart (l10n_ng or custom)."""

from collections import OrderedDict
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

PL_SECTIONS = [
    ("revenue", "Revenue", ["income"], -1),
    ("cos", "Cost of Sales", ["expense_direct_cost"], 1),
    ("other_income", "Other Income", ["income_other"], -1),
    ("opex", "Operating Expenses", ["expense"], 1),
    ("depreciation", "Depreciation & Amortisation", ["expense_depreciation"], 1),
]
PL_TYPES = [t for s in PL_SECTIONS for t in s[2]]

BS_SECTIONS = [
    ("nca", "Non-Current Assets", ["asset_fixed", "asset_non_current"], 1, "assets"),
    ("ca", "Current Assets", ["asset_receivable", "asset_current", "asset_prepayments", "asset_cash"], 1, "assets"),
    ("cl", "Current Liabilities", ["liability_payable", "liability_credit_card", "liability_current"], -1, "liabilities"),
    ("ncl", "Non-Current Liabilities", ["liability_non_current"], -1, "liabilities"),
    ("equity", "Equity", ["equity"], -1, "equity"),
]


class ArcoFinancialStatement(models.AbstractModel):
    _name = "arco.financial.statement"
    _description = "Financial statement engine"

    # ------------------------------------------------------------------ core
    @api.model
    def _base_domain(self, companies, posted_only=True):
        domain = [("company_id", "in", companies.ids), ("account_id.account_type", "!=", "off_balance")]
        if posted_only:
            domain.append(("parent_state", "=", "posted"))
        else:
            domain.append(("parent_state", "in", ("draft", "posted")))
        return domain

    @api.model
    def _balances(self, companies, date_from, date_to, types, posted_only=True):
        """{account: balance} for the account types and date range (date_from may be None)."""
        domain = self._base_domain(companies, posted_only) + [("account_id.account_type", "in", types)]
        if date_from:
            domain.append(("date", ">=", date_from))
        if date_to:
            domain.append(("date", "<=", date_to))
        groups = self.env["account.move.line"]._read_group(domain, ["account_id"], ["balance:sum"])
        return {account: balance for account, balance in groups}

    @api.model
    def _section(self, companies, date_from, date_to, types, sign, posted_only):
        bal = self._balances(companies, date_from, date_to, types, posted_only)
        lines = [
            {"code": acc.code, "name": acc.name, "amount": sign * amount}
            for acc, amount in sorted(bal.items(), key=lambda kv: kv[0].code or "")
            if not companies[:1].currency_id.is_zero(amount)
        ]
        return lines, sum(l["amount"] for l in lines)

    # ------------------------------------------------------------------ P&L
    @api.model
    def profit_and_loss(self, companies, date_from, date_to, posted_only=True):
        res = OrderedDict()
        for key, label, types, sign in PL_SECTIONS:
            lines, total = self._section(companies, date_from, date_to, types, sign, posted_only)
            res[key] = {"label": label, "lines": lines, "total": total}
        gross = res["revenue"]["total"] - res["cos"]["total"]
        operating = gross + res["other_income"]["total"] - res["opex"]["total"] - res["depreciation"]["total"]
        return {"sections": res, "gross_profit": gross, "net_profit": operating}

    # ------------------------------------------------------------------ BS
    @api.model
    def balance_sheet(self, companies, date_to, posted_only=True):
        company = companies[:1]
        fy_start = company.compute_fiscalyear_dates(fields.Date.to_date(date_to))["date_from"]
        res = OrderedDict()
        for key, label, types, sign, side in BS_SECTIONS:
            lines, total = self._section(companies, None, date_to, types, sign, posted_only)
            res[key] = {"label": label, "lines": lines, "total": total, "side": side}
        # earnings: current year P&L + everything before (retained) + unaffected earnings account
        cy = -sum(self._balances(companies, fy_start, date_to, PL_TYPES, posted_only).values())
        prior = -sum(self._balances(companies, None, fy_start - timedelta(days=1), PL_TYPES, posted_only).values())
        unaffected = -sum(self._balances(companies, None, date_to, ["equity_unaffected"], posted_only).values())
        res["equity"]["lines"] += [
            {"code": "", "name": _("Retained Earnings (prior years)"), "amount": prior + unaffected},
            {"code": "", "name": _("Current Year Earnings"), "amount": cy},
        ]
        res["equity"]["total"] += prior + unaffected + cy
        assets = res["nca"]["total"] + res["ca"]["total"]
        liabilities = res["cl"]["total"] + res["ncl"]["total"]
        equity = res["equity"]["total"]
        return {
            "sections": res,
            "total_assets": assets,
            "total_liabilities": liabilities,
            "total_equity": equity,
            "total_le": liabilities + equity,
            "difference": assets - liabilities - equity,
        }

    # ------------------------------------------------------------------ CF
    @api.model
    def cash_flow(self, companies, date_from, date_to, posted_only=True):
        """Indirect method. Every non-cash movement explains the change in cash, so the
        statement always reconciles to the cash & bank accounts."""
        mv = lambda types: sum(self._balances(companies, date_from, date_to, types, posted_only).values())  # noqa: E731
        net_profit = -mv(PL_TYPES)
        depreciation = mv(["expense_depreciation"])
        wc = [
            (_("(Increase)/decrease in trade receivables"), -mv(["asset_receivable"])),
            (_("(Increase)/decrease in other current assets"), -mv(["asset_current"])),
            (_("(Increase)/decrease in prepayments"), -mv(["asset_prepayments"])),
            (_("Increase/(decrease) in trade payables"), -mv(["liability_payable", "liability_credit_card"])),
            (_("Increase/(decrease) in other current liabilities (incl. VAT, WHT, NCD)"), -mv(["liability_current"])),
        ]
        operating = net_profit + depreciation + sum(a for _l, a in wc)
        investing_lines = [
            (_("Purchase / disposal of property, plant & equipment"), -mv(["asset_fixed"]) - depreciation),
            (_("Other non-current assets"), -mv(["asset_non_current"])),
        ]
        investing = sum(a for _l, a in investing_lines)
        financing_lines = [
            (_("Long-term borrowings raised / (repaid)"), -mv(["liability_non_current"])),
            (_("Equity movements (capital, dividends)"), -mv(["equity", "equity_unaffected"])),
        ]
        financing = sum(a for _l, a in financing_lines)
        net_change = operating + investing + financing
        opening = sum(self._balances(companies, None, date_from - timedelta(days=1), ["asset_cash"], posted_only).values())
        closing = sum(self._balances(companies, None, date_to, ["asset_cash"], posted_only).values())
        return {
            "net_profit": net_profit,
            "depreciation": depreciation,
            "working_capital": wc,
            "operating": operating,
            "investing_lines": investing_lines,
            "investing": investing,
            "financing_lines": financing_lines,
            "financing": financing,
            "net_change": net_change,
            "opening_cash": opening,
            "closing_cash": closing,
            "difference": opening + net_change - closing,
        }

    # ------------------------------------------------------------------ helpers
    @api.model
    def comparative_period(self, date_from, date_to, mode):
        if mode == "prior_year":
            return date_from - relativedelta(years=1), date_to - relativedelta(years=1)
        if mode == "prior_period":
            days = (date_to - date_from).days + 1
            return date_from - timedelta(days=days), date_from - timedelta(days=1)
        return None, None

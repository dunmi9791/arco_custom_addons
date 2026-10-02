from odoo import fields, models


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    def _arco_budget_account(self):
        self.ensure_one()
        if not self.product_id:
            return self.env["account.account"]
        accounts = self.product_id.product_tmpl_id.get_product_accounts(fiscal_pos=self.order_id.fiscal_position_id)
        return accounts.get("expense") or self.env["account.account"]


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def button_confirm(self):
        Budget = self.env["arco.budget.line"]
        for order in self.filtered(lambda o: o.state in ("draft", "sent", "to approve")):
            if order.arco_pr_preapproved:
                continue  # already checked when the requisition was submitted
            reqs = []
            for line in order.order_line.filtered(lambda l: not l.display_type and l.analytic_distribution):
                reqs.append({
                    "distribution": line.analytic_distribution,
                    "account": line._arco_budget_account(),
                    "amount": order.currency_id._convert(
                        line.price_subtotal, order.company_id.currency_id, order.company_id,
                        order.date_order or fields.Date.today()),
                    "date": (line.date_planned or order.date_order).date(),
                    "company": order.company_id,
                })
            Budget._arco_check_budget(reqs, order)
        return super().button_confirm()


class ArcoPurchaseRequestLine(models.Model):
    _inherit = "arco.purchase.request.line"

    def _arco_budget_account(self):
        self.ensure_one()
        accounts = self.product_id.product_tmpl_id.get_product_accounts()
        return accounts.get("expense") or self.env["account.account"]


class ArcoPurchaseRequest(models.Model):
    _inherit = "arco.purchase.request"

    def action_submit(self):
        Budget = self.env["arco.budget.line"]
        for rec in self:
            reqs = [{
                "distribution": line.analytic_distribution,
                "account": line._arco_budget_account(),
                "amount": line.subtotal,
                "date": rec.date_required or rec.date_request,
                "company": rec.company_id,
            } for line in rec.line_ids if line.analytic_distribution]
            Budget._arco_check_budget(reqs, rec)
        return super().action_submit()

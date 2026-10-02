from . import models
from .models.ncd import setup_ncd_taxes


def post_init_hook(env):
    for company in env["res.company"].search([("parent_id", "=", False)]):
        if env["account.account"].search_count([("company_ids", "in", company.id)], limit=1):
            setup_ncd_taxes(env, company)

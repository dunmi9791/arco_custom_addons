import binascii

from odoo import _, http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal


class ArcoContractPortal(CustomerPortal):

    @http.route(["/my/contracts/<int:contract_id>"], type="http", auth="public", website=True)
    def arco_portal_contract(self, contract_id, access_token=None, **kw):
        try:
            contract_sudo = self._document_check_access("arco.vendor.contract", contract_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect("/my")
        values = {
            "contract": contract_sudo,
            "token": access_token,
            "page_name": "arco_contract",
            "message": kw.get("message"),
        }
        return request.render("arco_vendor_contract.portal_contract_page", values)

    @http.route(["/my/contracts/<int:contract_id>/sign"], type="json", auth="public", website=True)
    def arco_portal_contract_sign(self, contract_id, access_token=None, name=None, signature=None):
        access_token = access_token or request.httprequest.args.get("access_token")
        try:
            contract_sudo = self._document_check_access("arco.vendor.contract", contract_id, access_token=access_token)
        except (AccessError, MissingError):
            return {"error": _("Invalid contract.")}
        if not contract_sudo._has_to_be_signed():
            return {"error": _("This contract is not waiting for your signature.")}
        if not signature:
            return {"error": _("Signature is missing.")}
        try:
            contract_sudo._arco_vendor_sign(name, signature)
            request.env.cr.flush()
        except (TypeError, binascii.Error):
            return {"error": _("Invalid signature data.")}
        return {
            "force_refresh": True,
            "redirect_url": contract_sudo.get_portal_url(query_string="&message=sign_ok"),
        }

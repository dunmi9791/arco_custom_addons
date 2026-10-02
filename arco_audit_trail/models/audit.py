import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

SKIP_FIELDS = {"write_date", "write_uid", "create_date", "create_uid", "__last_update", "message_main_attachment_id"}


def _fmt(value):
    if isinstance(value, tuple) and len(value) == 2:  # many2one from read()
        return value[1]
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if value is False or value is None:
        return ""
    return str(value)


class ArcoAuditRule(models.Model):
    _name = "arco.audit.rule"
    _description = "Audit Trail Rule"

    name = fields.Char(required=True)
    model_id = fields.Many2one("ir.model", required=True, ondelete="cascade")
    model_name = fields.Char(related="model_id.model", store=True)
    log_create = fields.Boolean(default=True)
    log_write = fields.Boolean(default=True)
    log_unlink = fields.Boolean(default=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [("model_uniq", "unique(model_id)", "One audit rule per model.")]

    # ------------------------------------------------------------------ patching
    def _register_hook(self):
        res = super()._register_hook()
        try:
            self._arco_patch_models()
        except Exception:  # never block the registry on audit problems
            _logger.exception("ARCO audit trail: could not patch models")
        return res

    @api.model
    def _arco_patch_models(self):
        rules = self.sudo().search([])
        for rule in rules:
            if rule.model_name not in self.env:
                continue
            cls = type(self.env[rule.model_name])
            if getattr(cls, "_arco_audit_patched", False):
                continue
            ArcoAuditRule._arco_patch_class(cls)
            cls._arco_audit_patched = True
            _logger.info("ARCO audit trail active on %s", rule.model_name)

    @staticmethod
    def _arco_patch_class(cls):
        orig_create = cls.create
        orig_write = cls.write
        orig_unlink = cls.unlink

        @api.model_create_multi
        def create(self, vals_list):
            records = orig_create(self, vals_list)
            rule = self.env["arco.audit.rule"]._arco_rule(self._name)
            if rule and rule.log_create and not self.env.context.get("arco_audit_skip"):
                fnames = set()
                for v in vals_list:
                    fnames |= set(v)
                self.env["arco.audit.log"]._arco_log(records, "create", fnames, {}, None)
            return records

        def write(self, vals):
            rule = self.env["arco.audit.rule"]._arco_rule(self._name)
            if not rule or not rule.log_write or self.env.context.get("arco_audit_skip"):
                return orig_write(self, vals)
            fnames = [f for f in vals if f in self._fields and self._fields[f].store and f not in SKIP_FIELDS
                      and self._fields[f].type not in ("one2many", "binary")]
            old = {r["id"]: r for r in self.sudo().with_context(prefetch_fields=False).read(fnames)} if fnames else {}
            res = orig_write(self, vals)
            if fnames:
                self.env["arco.audit.log"]._arco_log(self, "write", fnames, old, None)
            return res

        def unlink(self):
            rule = self.env["arco.audit.rule"]._arco_rule(self._name)
            if rule and rule.log_unlink and not self.env.context.get("arco_audit_skip"):
                self.env["arco.audit.log"]._arco_log(self, "unlink", [], {}, None)
            return orig_unlink(self)

        cls.create = create
        cls.write = write
        cls.unlink = unlink

    @api.model
    def _arco_rule(self, model_name):
        return self.sudo().search([("model_name", "=", model_name)], limit=1)


class ArcoAuditLog(models.Model):
    _name = "arco.audit.log"
    _description = "Audit Trail Entry"
    _order = "id desc"
    _rec_name = "res_name"

    date = fields.Datetime(default=fields.Datetime.now, readonly=True, index=True)
    user_id = fields.Many2one("res.users", readonly=True, index=True)
    model_id = fields.Many2one("ir.model", readonly=True, ondelete="cascade", index=True)
    model_name = fields.Char(readonly=True, index=True)
    res_id = fields.Integer("Record ID", readonly=True, index=True)
    res_name = fields.Char("Record", readonly=True)
    method = fields.Selection(
        [("create", "Created"), ("write", "Modified"), ("unlink", "Deleted")], readonly=True
    )
    line_ids = fields.One2many("arco.audit.log.line", "log_id", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)

    @api.model
    def _arco_log(self, records, method, fnames, old, _new):
        if not records:
            return
        model = self.env["ir.model"].sudo()._get(records._name)
        fnames = [f for f in fnames if f in records._fields and records._fields[f].store and f not in SKIP_FIELDS
                  and records._fields[f].type not in ("one2many", "binary")]
        new = {}
        if method != "unlink" and fnames:
            new = {r["id"]: r for r in records.sudo().with_context(prefetch_fields=False).read(fnames)}
        field_map = {f.name: f.id for f in model.field_id}
        vals_list = []
        for rec in records.sudo():
            lines = []
            for f in fnames:
                o = _fmt(old.get(rec.id, {}).get(f)) if method == "write" else ""
                n = _fmt(new.get(rec.id, {}).get(f))
                if method == "write" and o == n:
                    continue
                lines.append((0, 0, {"field_id": field_map.get(f), "old_value": o, "new_value": n}))
            if method == "write" and not lines:
                continue
            vals_list.append({
                "user_id": self.env.uid,
                "model_id": model.id,
                "model_name": records._name,
                "res_id": rec.id,
                "res_name": rec.display_name,
                "method": method,
                "company_id": rec.company_id.id if "company_id" in rec._fields and rec.company_id else self.env.company.id,
                "line_ids": lines,
            })
        if vals_list:
            self.sudo().with_context(arco_audit_skip=True).create(vals_list)

    def action_open_record(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": self.model_name, "res_id": self.res_id, "view_mode": "form"}


class ArcoAuditLogLine(models.Model):
    _name = "arco.audit.log.line"
    _description = "Audit Trail Field Change"

    log_id = fields.Many2one("arco.audit.log", required=True, ondelete="cascade", index=True)
    field_id = fields.Many2one("ir.model.fields", readonly=True, ondelete="cascade")
    field_description = fields.Char(related="field_id.field_description")
    old_value = fields.Text(readonly=True)
    new_value = fields.Text(readonly=True)

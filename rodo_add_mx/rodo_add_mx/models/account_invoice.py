# -*- coding: utf-8 -*-

from odoo import models, fields, api, Command, _
DEFAULT_CFDI_DATE_FORMAT = '%Y-%m-%dT%H:%M:%S'

class AccountInvoice(models.Model):
    _inherit = 'account.move'

    attachment_id = fields.Many2one("ir.attachment", 'Attachment Sync')
    l10n_mx_edi_cfdi_uuid_cusom = fields.Char(string='Fiscal Folio UUID', copy=False, readonly=True, compute="_compute_cfdi_uuid", store=True)
    hide_message = fields.Boolean(string='Hide Message', default=False, copy=False)

    @api.depends('l10n_mx_edi_cfdi_attachment_id')
    def _compute_cfdi_uuid(self):
        for inv in self:
            if not inv.l10n_mx_edi_cfdi_attachment_id:
                attachments = inv.attachment_ids
                results = []
                results += [rec for rec in attachments if rec.name.endswith('.xml')]
                if results:
                    domain = [('res_id', '=', inv.id),
                              ('res_model', '=', inv._name),
                              ('name', '=', results[0].name)]

                    attachment = inv.env['ir.attachment'].search(domain, limit=1)
                    if attachment and not inv.l10n_mx_edi_invoice_document_ids:

                         document_values = {
                               'move_id': inv.id,
                               'invoice_ids': [Command.set(inv.ids)],
                               'state': 'invoice_sent',
                               'sat_state': 'not_defined',
                               'message': None,
                               'attachment_id': attachment.id,
                               }
                         inv.env['l10n_mx_edi.document']._create_update_invoice_document_from_invoice(self, document_values)

            else:
                cfdi_infos = inv._compute_l10n_mx_edi_cfdi_uuid()
                inv.l10n_mx_edi_cfdi_uuid_cusom = cfdi_infos

    def run_cfdi_uuid(self):
        for inv in self:
            inv._compute_cfdi_uuid()
            inv.hide_message = True

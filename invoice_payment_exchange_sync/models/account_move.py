from odoo import _, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    payment_company_currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        string='Company Currency',
        readonly=True,
    )
    amount_mxn = fields.Monetary(
        string='Amount MXN',
        currency_field='payment_company_currency_id',
        help='If filled, Register Payment will use this amount in company currency.',
    )

    def action_register_mxn_payment(self):
        self.ensure_one()
        self._sync_invoice_rate_from_amount_mxn()
        return self.action_register_payment()

    def action_register_payment(self):
        action = super().action_register_payment()

        if len(self) != 1:
            return action

        if (
            self.move_type not in ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')
            or not self.currency_id
            or self.currency_id == self.company_id.currency_id
            or not self.amount_mxn
        ):
            return action

        action_context = dict(action.get('context', {}))
        action_context.update({
            'use_invoice_amount_mxn': True,
            'invoice_amount_mxn': self.amount_mxn,
            'invoice_company_currency_id': self.company_id.currency_id.id,
        })
        action['context'] = action_context
        return action

    def _sync_invoice_rate_from_amount_mxn(self):
        self.ensure_one()

        if self.move_type not in ('out_invoice', 'out_refund', 'in_invoice', 'in_refund'):
            raise UserError(_('This action is only available for invoices and bills.'))
        if self.state != 'posted':
            raise UserError(_('The invoice must be posted before syncing the MXN rate.'))
        if not self.currency_id or self.currency_id == self.company_id.currency_id:
            raise UserError(_('The invoice must use a foreign currency.'))
        if not self.amount_mxn or self.amount_mxn <= 0:
            raise UserError(_('Amount MXN must be greater than zero.'))
        if not self.amount_total or self.amount_total <= 0:
            raise UserError(_('The invoice total must be greater than zero.'))
        if 'invoice_currency_rate' not in self._fields:
            raise UserError(_('This Odoo version does not expose invoice_currency_rate on invoices.'))

        inverse_rate = self.amount_total / self.amount_mxn
        if inverse_rate <= 0:
            raise UserError(_('The calculated invoice exchange rate must be greater than zero.'))

        self._set_record_to_draft(self)
        self.with_context(check_move_validity=False).write({
            'invoice_currency_rate': inverse_rate,
        })
        self.action_post()

    def _set_record_to_draft(self, record):
        if hasattr(record, 'button_draft'):
            record.button_draft()
            return
        if hasattr(record, 'action_draft'):
            record.action_draft()
            return
        raise UserError(_('Cannot set %s to draft.') % (record.display_name,))

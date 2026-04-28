from odoo import fields, models


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

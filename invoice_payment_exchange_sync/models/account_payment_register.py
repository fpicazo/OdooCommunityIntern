from odoo import api, models


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if not self.env.context.get('use_invoice_amount_mxn'):
            return values

        amount_mxn = self.env.context.get('invoice_amount_mxn')
        company_currency_id = self.env.context.get('invoice_company_currency_id')

        if amount_mxn:
            values['amount'] = amount_mxn
        if company_currency_id and 'currency_id' in self._fields:
            values['currency_id'] = company_currency_id
        return values

    def _create_payments(self):
        payments = super()._create_payments()
        if not self.env.context.get('sync_invoice_rate_after_payment'):
            return payments

        invoices = self.env['account.move'].browse(self.env.context.get('active_ids', [])).exists()
        if len(invoices) != 1 or len(payments) != 1:
            return payments

        invoices._sync_invoice_rate_from_amount_mxn(payment=payments[:1])
        return payments

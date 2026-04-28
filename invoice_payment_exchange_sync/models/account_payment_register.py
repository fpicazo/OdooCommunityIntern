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
        payment_date_mxn = self.env.context.get('invoice_payment_date_mxn')

        if amount_mxn:
            values['amount'] = amount_mxn
        if company_currency_id and 'currency_id' in self._fields:
            values['currency_id'] = company_currency_id
        if payment_date_mxn and 'payment_date' in self._fields:
            values['payment_date'] = payment_date_mxn
        return values

    def _create_payments(self):
        if self.env.context.get('sync_invoice_rate_after_payment'):
            self._apply_invoice_rate_on_payment_date()
        payments = super()._create_payments()
        if not self.env.context.get('sync_invoice_rate_after_payment'):
            return payments

        invoices = self.env['account.move'].browse(self.env.context.get('active_ids', [])).exists()
        if len(invoices) != 1 or len(payments) != 1:
            return payments

        invoices._sync_invoice_rate_from_amount_mxn(payment=payments[:1])
        return payments

    def _apply_invoice_rate_on_payment_date(self):
        invoices = self.env['account.move'].browse(self.env.context.get('active_ids', [])).exists()
        if len(invoices) != 1:
            return

        invoice = invoices[:1]
        if (
            not invoice.amount_mxn
            or not invoice.amount_total
            or not invoice.currency_id
            or invoice.currency_id == invoice.company_id.currency_id
        ):
            return

        exchange_rate = invoice.amount_mxn / invoice.amount_total
        payment_date = getattr(self, 'payment_date', False) or invoice.invoice_date
        rate_model = self.env['res.currency.rate'].sudo()
        rate_vals = {
            'name': payment_date,
            'currency_id': invoice.currency_id.id,
        }
        if 'company_id' in rate_model._fields:
            rate_vals['company_id'] = invoice.company_id.id
        if 'inverse_company_rate' in rate_model._fields:
            rate_vals['inverse_company_rate'] = exchange_rate
        elif 'company_rate' in rate_model._fields:
            rate_vals['company_rate'] = exchange_rate
        elif 'rate' in rate_model._fields:
            rate_vals['rate'] = 1.0 / exchange_rate
        else:
            return

        domain = [
            ('currency_id', '=', invoice.currency_id.id),
            ('name', '=', payment_date),
        ]
        if 'company_id' in rate_model._fields:
            domain.append(('company_id', '=', invoice.company_id.id))

        existing_rate = rate_model.search(domain, limit=1)
        if existing_rate:
            existing_rate.write(rate_vals)
        else:
            rate_model.create(rate_vals)

from odoo import _, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_sync_existing_payments_exchange_rate(self):
        self.ensure_one()

        if self.move_type not in ('out_invoice', 'out_refund', 'in_invoice', 'in_refund'):
            raise UserError(_('This action is only available for invoices and bills.'))

        if self.state != 'posted':
            raise UserError(_('You can only sync payments from a posted invoice.'))

        company_currency = self.company_id.currency_id
        if not self.currency_id or self.currency_id == company_currency:
            raise UserError(_('This invoice does not use a foreign currency exchange rate.'))

        payments = self._get_linked_payments()
        if not payments:
            raise UserError(_('No existing payments are linked to this invoice.'))

        exchange_rate = self._get_invoice_exchange_rate()
        if not exchange_rate:
            raise UserError(_('Could not determine the exchange rate for invoice %s.') % (self.display_name,))

        synced_count = 0
        for payment in payments:
            if self._convert_payment_to_company_currency(payment, exchange_rate):
                synced_count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Payments Converted'),
                'message': _(
                    'Converted %s existing payment(s) to %s using the invoice exchange rate.'
                ) % (
                    synced_count,
                    self.company_id.currency_id.name,
                ),
                'type': 'success',
                'sticky': False,
            }
        }

    def _get_linked_payments(self):
        self.ensure_one()
        receivable_payable_lines = self.line_ids.filtered(
            lambda line: line.account_id.account_type in ('asset_receivable', 'liability_payable')
        )
        partial_reconciles = receivable_payable_lines.matched_debit_ids | receivable_payable_lines.matched_credit_ids
        payment_moves = (
            partial_reconciles.debit_move_id.move_id | partial_reconciles.credit_move_id.move_id
        ).filtered(lambda move: move != self)
        payments = self.env['account.payment'].browse()

        if 'payment_id' in payment_moves._fields:
            payments |= payment_moves.mapped('payment_id')
        if payment_moves:
            payments |= self.env['account.payment'].search([('move_id', 'in', payment_moves.ids)])
        return payments

    def _get_invoice_exchange_rate(self):
        self.ensure_one()
        invoice_currency_rate = self._fields.get('invoice_currency_rate')
        if invoice_currency_rate and self.invoice_currency_rate:
            return 1.0 / self.invoice_currency_rate

        rate_date = self.invoice_date or fields.Date.context_today(self)
        conversion_method = getattr(self.currency_id, '_get_conversion_rate', None)
        if conversion_method:
            return conversion_method(
                self.currency_id, self.company_id.currency_id, self.company_id, rate_date
            )

        rate_model = self.env['res.currency.rate'].sudo()
        domain = [
            ('currency_id', '=', self.currency_id.id),
            ('name', '<=', rate_date),
        ]
        if 'company_id' in rate_model._fields:
            domain.append(('company_id', 'in', [self.company_id.id, False]))

        existing_rate = rate_model.search(domain, order='name desc', limit=1)
        if not existing_rate:
            return False
        if 'inverse_company_rate' in existing_rate._fields and existing_rate.inverse_company_rate:
            return existing_rate.inverse_company_rate
        if 'company_rate' in existing_rate._fields and existing_rate.company_rate:
            return existing_rate.company_rate
        if 'rate' in existing_rate._fields and existing_rate.rate:
            return 1.0 / existing_rate.rate
        return False

    def _convert_payment_to_company_currency(self, payment, exchange_rate):
        self.ensure_one()
        company_currency = self.company_id.currency_id
        payment_currency = payment.currency_id or company_currency

        if payment_currency == company_currency:
            return False

        converted_amount = company_currency.round(payment.amount * exchange_rate)
        if converted_amount <= 0:
            raise UserError(
                _('Converted MXN amount must be greater than zero for payment %s.')
                % (payment.display_name,)
            )

        account_internal_group = self._get_payment_account_internal_group()
        payment_move = payment.move_id
        counterpart_line = self._get_payment_counterpart_line(payment, account_internal_group)
        foreign_currency = counterpart_line.currency_id or self.currency_id
        foreign_amount = counterpart_line.amount_currency

        if payment_move and payment_move.line_ids:
            payment_move.line_ids.remove_move_reconcile()

        if payment.state == 'posted':
            self._set_record_to_draft(payment)

        write_vals = {
            'currency_id': company_currency.id,
            'amount': converted_amount,
        }
        if 'date' in payment._fields and payment.date:
            write_vals['date'] = payment.date
        payment.write(write_vals)
        self._rewrite_payment_move_lines(
            payment=payment,
            account_internal_group=account_internal_group,
            foreign_currency=foreign_currency,
            foreign_amount=foreign_amount,
        )

        if payment.state != 'posted':
            payment.action_post()

        self._reconcile_payment_with_invoice(payment, account_internal_group)
        return True

    def _get_payment_account_internal_group(self):
        self.ensure_one()
        if self.move_type in ('out_invoice', 'out_refund'):
            return 'receivable'
        return 'payable'

    def _set_record_to_draft(self, record):
        if hasattr(record, 'button_draft'):
            record.button_draft()
            return
        if hasattr(record, 'action_draft'):
            record.action_draft()
            return
        raise UserError(_('Cannot set %s to draft.') % (record.display_name,))

    def _get_payment_counterpart_line(self, payment, account_internal_group):
        expected_account_type = (
            'asset_receivable' if account_internal_group == 'receivable' else 'liability_payable'
        )
        counterpart_line = payment.move_id.line_ids.filtered(
            lambda line: line.account_id.internal_group == account_internal_group
        )[:1]
        if not counterpart_line:
            counterpart_line = payment.move_id.line_ids.filtered(
                lambda line: line.account_id.account_type == expected_account_type
            )[:1]
        if not counterpart_line:
            raise UserError(
                _('Could not find the receivable/payable line for payment %s.')
                % (payment.display_name,)
            )
        return counterpart_line

    def _rewrite_payment_move_lines(self, payment, account_internal_group, foreign_currency, foreign_amount):
        payment_move = payment.move_id
        if not payment_move:
            raise UserError(_('Payment %s has no journal entry.') % (payment.display_name,))

        counterpart_line = self._get_payment_counterpart_line(payment, account_internal_group)
        liquidity_lines = payment_move.line_ids - counterpart_line

        counterpart_vals = {
            'currency_id': foreign_currency.id if foreign_currency else False,
            'amount_currency': foreign_amount,
        }
        counterpart_line.write(counterpart_vals)

        for liquidity_line in liquidity_lines:
            liquidity_line.write({
                'currency_id': False,
                'amount_currency': 0.0,
            })

    def _reconcile_payment_with_invoice(self, payment, account_internal_group):
        self.ensure_one()
        expected_account_type = (
            'asset_receivable' if account_internal_group == 'receivable' else 'liability_payable'
        )

        self.invalidate_recordset()
        payment.invalidate_recordset()

        invoice_lines = self.line_ids.filtered(
            lambda line: not line.reconciled and line.account_id.internal_group == account_internal_group
        )
        if not invoice_lines:
            invoice_lines = self.line_ids.filtered(
                lambda line: not line.reconciled and line.account_id.account_type == expected_account_type
            )

        payment_lines = payment.move_id.line_ids.filtered(
            lambda line: not line.reconciled and line.account_id.internal_group == account_internal_group
        )
        if not payment_lines:
            payment_lines = payment.move_id.line_ids.filtered(
                lambda line: not line.reconciled and line.account_id.account_type == expected_account_type
            )

        lines_to_reconcile = invoice_lines + payment_lines
        if not lines_to_reconcile:
            raise UserError(
                _('Could not find lines to reconcile for payment %s.') % (payment.display_name,)
            )

        lines_to_reconcile.reconcile()

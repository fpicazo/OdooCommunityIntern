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
        if len(payments) > 1:
            raise UserError(
                _('This action currently supports invoices with exactly one linked payment.')
            )

        payment = payments[:1]
        exchange_rate = self._get_payment_exchange_rate(payment)
        if not exchange_rate:
            raise UserError(
                _('Could not determine the exchange rate from payment %s.') % (payment.display_name,)
            )

        self._sync_invoice_to_payment_rate(payment, exchange_rate)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Invoice Rate Updated'),
                'message': _(
                    'Updated invoice %s to use the exchange rate from payment %s.'
                ) % (
                    self.display_name,
                    payment.display_name,
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

    def _get_payment_exchange_rate(self, payment):
        self.ensure_one()
        account_internal_group = self._get_payment_account_internal_group()
        counterpart_line = self._get_payment_counterpart_line(payment, account_internal_group)
        foreign_amount = abs(counterpart_line.amount_currency)
        company_amount = abs(counterpart_line.balance)

        if not foreign_amount or not company_amount:
            return False
        return company_amount / foreign_amount

    def _sync_invoice_to_payment_rate(self, payment, exchange_rate):
        self.ensure_one()
        account_internal_group = self._get_payment_account_internal_group()
        exchange_moves = self._get_exchange_difference_moves()

        self._remove_reconciliation_with_payment(payment)
        self._remove_exchange_difference_moves(exchange_moves)

        was_posted = self.state == 'posted'
        if was_posted:
            self._set_record_to_draft(self)

        inverse_rate = 1.0 / exchange_rate
        write_vals = {}
        if 'invoice_currency_rate' in self._fields:
            write_vals['invoice_currency_rate'] = inverse_rate
        if 'date' in payment._fields and payment.date and self.invoice_date != payment.date:
            write_vals['invoice_date'] = payment.date
        if write_vals:
            self.with_context(check_move_validity=False).write(write_vals)

        if was_posted:
            self.action_post()

        self._reconcile_payment_with_invoice(payment, account_internal_group)

    def _remove_reconciliation_with_payment(self, payment):
        self.ensure_one()
        lines = self.line_ids | payment.move_id.line_ids
        if lines:
            lines.remove_move_reconcile()

    def _get_exchange_difference_moves(self):
        self.ensure_one()
        return (
            self.line_ids.matched_debit_ids.exchange_move_id
            | self.line_ids.matched_credit_ids.exchange_move_id
        ).filtered(lambda move: move)

    def _remove_exchange_difference_moves(self, moves):
        for move in moves.filtered(lambda m: m.state == 'posted'):
            self._set_record_to_draft(move)
            move.with_context(force_delete=True).unlink()

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

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
        if not self.amount_mxn or self.amount_mxn <= 0:
            raise UserError(_('Amount MXN must be greater than zero.'))
        if self.state != 'posted':
            raise UserError(_('The invoice must be posted before registering the MXN payment.'))

        action_context = dict(self.env.context)
        action_context.update({
            'use_invoice_amount_mxn': True,
            'invoice_amount_mxn': self.amount_mxn,
            'invoice_company_currency_id': self.company_id.currency_id.id,
            'sync_invoice_rate_after_payment': True,
            'active_model': 'account.move',
            'active_ids': self.ids,
            'active_id': self.id,
        })
        register = self.env['account.payment.register'].with_context(action_context).create({})
        if hasattr(register, 'action_create_payments'):
            register.action_create_payments()
        else:
            register._create_payments()
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def _sync_invoice_rate_from_amount_mxn(self, payment=None):
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

        exchange_moves = self._get_exchange_difference_moves()
        if payment:
            self._remove_reconciliation_with_payment(payment)
        self._remove_exchange_difference_moves(exchange_moves)
        self._set_record_to_draft(self)
        self.with_context(check_move_validity=False).write({
            'invoice_currency_rate': inverse_rate,
        })
        self.action_post()
        if payment:
            self._reconcile_payment_with_invoice(payment)

    def _set_record_to_draft(self, record):
        if hasattr(record, 'button_draft'):
            record.button_draft()
            return
        if hasattr(record, 'action_draft'):
            record.action_draft()
            return
        raise UserError(_('Cannot set %s to draft.') % (record.display_name,))

    def _get_payment_account_internal_group(self):
        self.ensure_one()
        if self.move_type in ('out_invoice', 'out_refund'):
            return 'receivable'
        return 'payable'

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

    def _reconcile_payment_with_invoice(self, payment):
        self.ensure_one()
        account_internal_group = self._get_payment_account_internal_group()
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

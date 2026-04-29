import logging

from odoo import _, models


_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _inherit = "account.payment"

    def _run_debug_query(self, query, params=()):
        cr = self.env.cr
        with cr.savepoint():
            cr.execute(query, params)
            return cr.fetchall()

    def _collect_delete_debug_info(self, payment_id, move_id=None):
        debug = {
            "payment_id": payment_id,
            "move_id": move_id or False,
        }

        try:
            rows = self._run_debug_query(
                "SELECT id, move_id, state, payment_type FROM account_payment WHERE id = %s",
                (payment_id,),
            )
            row = rows[0] if rows else False
            debug["payment_row"] = row or False
        except Exception as err:
            debug["payment_row_error"] = str(err)

        resolved_move_id = move_id
        if resolved_move_id is None and debug.get("payment_row"):
            resolved_move_id = debug["payment_row"][1]
            debug["move_id"] = resolved_move_id or False

        if resolved_move_id:
            try:
                rows = self._run_debug_query(
                    "SELECT id, state, name FROM account_move WHERE id = %s",
                    (resolved_move_id,),
                )
                debug["move_row"] = rows[0] if rows else False
            except Exception as err:
                debug["move_row_error"] = str(err)

            try:
                rows = self._run_debug_query(
                    "SELECT COUNT(*) FROM account_move_line WHERE move_id = %s",
                    (resolved_move_id,),
                )
                debug["move_line_count"] = rows[0][0] if rows else 0
            except Exception as err:
                debug["move_line_count_error"] = str(err)

            try:
                rows = self._run_debug_query(
                    """
                    SELECT COUNT(DISTINCT move.id)
                    FROM account_move_line payment_line
                    JOIN account_partial_reconcile apr
                        ON apr.debit_move_id = payment_line.id
                        OR apr.credit_move_id = payment_line.id
                    JOIN account_move_line counterpart_line
                        ON (
                            (apr.debit_move_id = counterpart_line.id AND apr.credit_move_id = payment_line.id)
                            OR
                            (apr.credit_move_id = counterpart_line.id AND apr.debit_move_id = payment_line.id)
                        )
                    JOIN account_move move
                        ON move.id = counterpart_line.move_id
                    WHERE payment_line.move_id = %s
                      AND move.move_type IN ('in_invoice', 'in_refund')
                    """,
                    (resolved_move_id,),
                )
                debug["linked_vendor_bill_count"] = rows[0][0] if rows else 0
            except Exception as err:
                debug["linked_vendor_bill_count_error"] = str(err)

        return debug

    def _sql_force_delete_selected_payment(self, payment_id=None, move_id=None):
        cr = self.env.cr
        if payment_id is None:
            self.ensure_one()
            payment_id = self.id
        if move_id is None:
            cr.execute("SELECT move_id FROM account_payment WHERE id = %s FOR UPDATE", (payment_id,))
            row = cr.fetchone()
            move_id = row[0] if row and row[0] else False
        else:
            # Acquire exclusive lock on the payment row to avoid concurrent-update errors.
            cr.execute("SELECT id FROM account_payment WHERE id = %s FOR UPDATE", (payment_id,))

        # Acquire exclusive lock on the move row before touching it.
        if move_id:
            cr.execute("SELECT id FROM account_move WHERE id = %s FOR UPDATE", (move_id,))

        # Clear FK references that might block deletion.
        # Wrap each in a savepoint so a failure rolls back cleanly and does
        # NOT leave the transaction in an aborted state.
        for _nullable_sql in [
            "UPDATE account_move SET payment_id = NULL WHERE payment_id = %s",
            "UPDATE account_bank_statement_line SET payment_id = NULL WHERE payment_id = %s",
        ]:
            try:
                with cr.savepoint():
                    cr.execute(_nullable_sql, (payment_id,))
            except Exception:
                pass

        cr.execute("DELETE FROM account_payment WHERE id = %s", (payment_id,))
        if move_id:
            cr.execute(
                "DELETE FROM account_partial_reconcile "
                "WHERE debit_move_id IN (SELECT id FROM account_move_line WHERE move_id = %s) "
                "   OR credit_move_id IN (SELECT id FROM account_move_line WHERE move_id = %s)",
                (move_id, move_id),
            )
            cr.execute("DELETE FROM account_move_line WHERE move_id = %s", (move_id,))
            cr.execute("DELETE FROM account_move WHERE id = %s", (move_id,))

    def _is_missing_move_delete_error(self, error):
        message = str(error or "").lower()
        return (
            "no es posible confirmar un pago" in message
            and "si no tiene un asiento contable" in message
        )

    def _is_transaction_aborted_error(self, error):
        message = str(error or "").lower()
        return "current transaction is aborted" in message

    def _get_invoice_related_documents(self):
        self.ensure_one()
        payment_lines = self.move_id.line_ids
        partials = payment_lines.matched_debit_ids | payment_lines.matched_credit_ids
        counterpart_lines = (partials.debit_move_id | partials.credit_move_id) - payment_lines
        return counterpart_lines.mapped("move_id").filtered(
            lambda move: move.move_type in ("out_invoice", "out_refund", "in_invoice", "in_refund")
        )

    def _is_unlinked_bill_payment(self):
        self.ensure_one()
        if self.payment_type != "outbound":
            return False
        if "partner_type" in self._fields and self.partner_type != "supplier":
            return False
        if "is_internal_transfer" in self._fields and self.is_internal_transfer:
            return False
        return not self._get_invoice_related_documents().filtered(
            lambda move: move.move_type in ("in_invoice", "in_refund")
        )

    def action_delete_all_unlinked_bill_payments(self):
        """Search all unlinked outbound vendor bill payments and delete them."""
        domain = [('payment_type', '=', 'outbound')]
        if 'partner_type' in self._fields:
            domain.append(('partner_type', '=', 'supplier'))
        if 'is_internal_transfer' in self._fields:
            domain.append(('is_internal_transfer', '=', False))

        candidates = self.env['account.payment'].sudo().search(domain)
        unlinked = candidates.filtered(lambda p: p._is_unlinked_bill_payment())

        _logger.info(
            "action_delete_all_unlinked_bill_payments: found %s candidates, %s unlinked",
            len(candidates),
            len(unlinked),
        )

        if not unlinked:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Bill Payments Cleanup'),
                    'message': _('No unlinked vendor bill payments found.'),
                    'type': 'info',
                    'sticky': False,
                },
            }

        return unlinked.action_delete_unlinked_bill_payments()

    def action_delete_unlinked_bill_payments(self):
        payments_to_delete = self.exists()

        deleted_count = 0
        skipped = []
        for payment in payments_to_delete:
            payment_id = payment.id
            debug_info = self._collect_delete_debug_info(payment_id)
            payment_row = debug_info.get("payment_row") or ()
            payment_name = payment.display_name
            payment_move_id = payment_row[1] if len(payment_row) > 1 and payment_row[1] else False
            payment_state = payment_row[2] if len(payment_row) > 2 else False
            move_row = debug_info.get("move_row") or ()
            move_exists = bool(move_row)
            payment_move = self.env["account.move"].sudo().browse(payment_move_id) if payment_move_id and move_exists else self.env["account.move"].sudo().browse()

            _logger.info(
                "Starting selected payment delete for %s (%s). debug=%s",
                payment_name,
                payment_id,
                debug_info,
            )
            try:
                with self.env.cr.savepoint():
                    payment_record = self.sudo().browse(payment_id).exists()
                    if not payment_record:
                        _logger.warning(
                            "Delete step 0 for %s (%s): payment no longer exists before delete",
                            payment_name,
                            payment_id,
                        )
                        deleted_count += 1
                        continue
                    _logger.info(
                        "Delete step 1 for %s (%s): entered savepoint. move_id=%s state=%s",
                        payment_name,
                        payment_id,
                        payment_move_id,
                        payment_state,
                    )
                    if payment_move and payment_move.line_ids:
                        _logger.info(
                            "Delete step 2 for %s (%s): removing reconciliations from move %s",
                            payment_name,
                            payment_id,
                            payment_move_id,
                        )
                        payment_move.line_ids.remove_move_reconcile()
                    if payment_state == "posted" and not payment_move_id:
                        _logger.warning(
                            "Delete step 3 for %s (%s): posted payment without move, forcing SQL delete. debug=%s",
                            payment_name,
                            payment_id,
                            debug_info,
                        )
                        self._sql_force_delete_selected_payment(payment_id=payment_id, move_id=False)
                        deleted_count += 1
                        continue
                    if payment_state == "posted" and hasattr(payment_record, "action_draft"):
                        _logger.info(
                            "Delete step 4 for %s (%s): moving payment to draft",
                            payment_name,
                            payment_id,
                        )
                        payment_record.action_draft()
                    _logger.info(
                        "Delete step 5 for %s (%s): unlink with forced context",
                        payment_name,
                        payment_id,
                    )
                    payment_record.with_context(
                        force_delete=True,
                        check_move_validity=False,
                        skip_account_move_synchronization=True,
                    ).unlink()
                    _logger.info(
                        "Delete step 6 for %s (%s): ORM unlink completed",
                        payment_name,
                        payment_id,
                    )
                deleted_count += 1
            except Exception as err:
                _logger.exception(
                    "Delete primary path failed for %s (%s). move_id=%s state=%s debug=%s",
                    payment_name,
                    payment_id,
                    payment_move_id,
                    payment_state,
                    debug_info,
                )
                # Always attempt a direct SQL delete as fallback.
                # Use a savepoint so a failure here does not abort the
                # main transaction and roll back previously deleted payments.
                try:
                    with self.env.cr.savepoint():
                        self._sql_force_delete_selected_payment(
                            payment_id=payment_id,
                            move_id=payment_move_id,
                        )
                    _logger.info(
                        "Delete fallback completed for %s (%s)",
                        payment_name,
                        payment_id,
                    )
                    deleted_count += 1
                    continue
                except Exception as force_err:
                    _logger.exception(
                        "Delete fallback failed for %s (%s). initial_error=%s force_error=%s",
                        payment_name,
                        payment_id,
                        err,
                        force_err,
                    )

                _logger.exception(
                    "Failed to delete selected payment %s (%s): %s",
                    payment_name,
                    payment_id,
                    err,
                )
                skipped.append("%s (%s)" % (payment_name, err))

        message = _(
            "Deleted %(deleted)s selected payment(s) out of %(found)s."
        ) % {
            "deleted": deleted_count,
            "found": len(payments_to_delete),
        }
        if skipped:
            message = _(
                "%(message)s %(skipped)s payment(s) were skipped."
            ) % {
                "message": message,
                "skipped": len(skipped),
            }
            message = "%s\n%s" % (message, "\n".join(skipped[:3]))

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Bill Payments Cleanup"),
                "message": message,
                "type": "warning" if skipped else "success",
                "sticky": bool(skipped),
            },
        }

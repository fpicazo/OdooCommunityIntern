import logging

from odoo import _, models


_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _inherit = "account.payment"

    def _collect_delete_debug_info(self, payment_id, move_id=None):
        cr = self.env.cr
        debug = {
            "payment_id": payment_id,
            "move_id": move_id or False,
        }

        try:
            cr.execute(
                "SELECT id, move_id, state, payment_type FROM account_payment WHERE id = %s",
                (payment_id,),
            )
            row = cr.fetchone()
            debug["payment_row"] = row or False
        except Exception as err:
            debug["payment_row_error"] = str(err)

        resolved_move_id = move_id
        if resolved_move_id is None and debug.get("payment_row"):
            resolved_move_id = debug["payment_row"][1]
            debug["move_id"] = resolved_move_id or False

        if resolved_move_id:
            try:
                cr.execute("SELECT id, state, name, payment_id FROM account_move WHERE id = %s", (resolved_move_id,))
                debug["move_row"] = cr.fetchone() or False
            except Exception as err:
                debug["move_row_error"] = str(err)

            try:
                cr.execute("SELECT COUNT(*) FROM account_move_line WHERE move_id = %s", (resolved_move_id,))
                debug["move_line_count"] = cr.fetchone()[0]
            except Exception as err:
                debug["move_line_count_error"] = str(err)

            try:
                cr.execute(
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
                debug["linked_vendor_bill_count"] = cr.fetchone()[0]
            except Exception as err:
                debug["linked_vendor_bill_count_error"] = str(err)

        return debug

    def _sql_force_delete_selected_payment(self, payment_id=None, move_id=None):
        cr = self.env.cr
        if payment_id is None:
            self.ensure_one()
            payment_id = self.id
        if move_id is None:
            cr.execute("SELECT move_id FROM account_payment WHERE id = %s", (payment_id,))
            row = cr.fetchone()
            move_id = row[0] if row and row[0] else False

        # Some Odoo versions keep a reverse pointer from move to payment.
        try:
            cr.execute("UPDATE account_move SET payment_id = NULL WHERE payment_id = %s", (payment_id,))
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

    def action_delete_unlinked_bill_payments(self):
        payments_to_delete = self.exists()

        deleted_count = 0
        skipped = []
        for payment in payments_to_delete:
            payment_id = payment.id
            debug_info = self._collect_delete_debug_info(payment_id)
            payment_row = debug_info.get("payment_row") or ()
            payment_name = payment_row[0] if len(payment_row) > 0 and payment_row[0] else payment.display_name
            payment_move_id = payment_row[1] if len(payment_row) > 1 and payment_row[1] else False
            payment_state = payment_row[2] if len(payment_row) > 2 else False
            payment_move = (
                self.env["account.move"].sudo().browse(payment_move_id).exists()
                if payment_move_id else self.env["account.move"].sudo().browse()
            )

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
                try:
                    if not payment_move_id or self._is_missing_move_delete_error(err):
                        _logger.warning(
                            "Delete fallback for %s (%s): rolling back transaction before SQL force delete",
                            payment_name,
                            payment_id,
                        )
                        self.env.cr.rollback()
                        fallback_debug = self._collect_delete_debug_info(payment_id, payment_move_id)
                        _logger.info(
                            "Delete fallback probe for %s (%s): debug=%s",
                            payment_name,
                            payment_id,
                            fallback_debug,
                        )
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
                    try:
                        self.env.cr.rollback()
                    except Exception:
                        pass
                    _logger.exception(
                        "Delete fallback failed for %s (%s). initial_error=%s",
                        payment_name,
                        payment_id,
                        err,
                    )
                    err = force_err

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

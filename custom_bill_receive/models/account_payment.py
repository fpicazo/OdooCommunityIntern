import logging

from odoo import _, models


_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _inherit = "account.payment"

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
            payment_name = payment.display_name
            payment_move = payment.move_id
            payment_move_id = payment_move.id if payment_move else False
            payment_state = payment.state

            if not payment._is_unlinked_bill_payment():
                skipped.append(
                    _("%s (selected payment is still linked to a vendor bill or is not a vendor payment)")
                    % payment_name
                )
                continue
            try:
                with self.env.cr.savepoint():
                    if payment_move and payment_move.line_ids:
                        payment_move.line_ids.remove_move_reconcile()
                    if payment_state == "posted" and not payment_move_id:
                        payment._sql_force_delete_selected_payment(payment_id=payment_id, move_id=False)
                        deleted_count += 1
                        continue
                    if payment_state == "posted" and hasattr(payment, "action_draft"):
                        payment.action_draft()
                    payment.with_context(
                        force_delete=True,
                        check_move_validity=False,
                        skip_account_move_synchronization=True,
                    ).unlink()
                deleted_count += 1
            except Exception as err:
                try:
                    if not payment_move_id or payment._is_missing_move_delete_error(err):
                        self.env.cr.rollback()
                        self._sql_force_delete_selected_payment(
                            payment_id=payment_id,
                            move_id=payment_move_id,
                        )
                        deleted_count += 1
                        continue
                except Exception as force_err:
                    try:
                        self.env.cr.rollback()
                    except Exception:
                        pass
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

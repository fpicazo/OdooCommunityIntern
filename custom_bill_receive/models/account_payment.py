from odoo import _, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

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
        payment_domain = [("payment_type", "=", "outbound")]
        if "partner_type" in self._fields:
            payment_domain.append(("partner_type", "=", "supplier"))
        if "is_internal_transfer" in self._fields:
            payment_domain.append(("is_internal_transfer", "=", False))

        payments = self.search(payment_domain)
        payments_to_delete = payments.filtered("_is_unlinked_bill_payment")

        deleted_count = 0
        skipped = []
        for payment in payments_to_delete:
            try:
                with self.env.cr.savepoint():
                    if payment.move_id and payment.move_id.line_ids:
                        payment.move_id.line_ids.remove_move_reconcile()
                    if payment.state == "posted" and hasattr(payment, "action_draft"):
                        payment.action_draft()
                    payment.unlink()
                deleted_count += 1
            except Exception as err:
                skipped.append("%s (%s)" % (payment.display_name, err))

        message = _(
            "Deleted %(deleted)s unlinked bill payments out of %(found)s candidates."
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

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Bill Payments Cleanup"),
                "message": message,
                "type": "warning" if skipped else "success",
                "sticky": bool(skipped),
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

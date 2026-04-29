import logging

from odoo import _, models

_logger = logging.getLogger(__name__)


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def action_force_delete_move_lines(self):
        """Force-delete selected journal items (apuntes contables) via SQL.

        Removes reconciliation entries first, then the lines themselves.
        Each line is handled in its own savepoint so one failure does not
        abort the whole batch.
        """
        lines_to_delete = self.exists()
        if not lines_to_delete:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Delete Journal Items"),
                    "message": _("No records found to delete."),
                    "type": "info",
                    "sticky": False,
                },
            }

        cr = self.env.cr
        deleted_count = 0
        skipped = []

        for line in lines_to_delete:
            line_id = line.id
            line_name = line.display_name or str(line_id)
            try:
                with cr.savepoint():
                    # Acquire exclusive lock to avoid concurrent-update errors.
                    cr.execute(
                        "SELECT id FROM account_move_line WHERE id = %s FOR UPDATE",
                        (line_id,),
                    )
                    if not cr.fetchone():
                        deleted_count += 1
                        continue

                    # Remove partial reconcile entries that reference this line.
                    cr.execute(
                        "DELETE FROM account_partial_reconcile "
                        "WHERE debit_move_id = %s OR credit_move_id = %s",
                        (line_id, line_id),
                    )

                    # Remove full reconcile if this line is part of one.
                    cr.execute(
                        """
                        DELETE FROM account_full_reconcile
                        WHERE id IN (
                            SELECT reconciled_line_ids.full_reconcile_id
                            FROM account_move_line reconciled_line_ids
                            WHERE reconciled_line_ids.id = %s
                        )
                        """,
                        (line_id,),
                    )

                    cr.execute(
                        "DELETE FROM account_move_line WHERE id = %s",
                        (line_id,),
                    )
                deleted_count += 1
                _logger.info("Force-deleted account.move.line %s (%s)", line_name, line_id)
            except Exception as err:
                _logger.exception(
                    "Failed to force-delete account.move.line %s (%s): %s",
                    line_name,
                    line_id,
                    err,
                )
                skipped.append("%s (%s)" % (line_name, err))

        message = _(
            "Deleted %(deleted)s journal item(s) out of %(total)s."
        ) % {"deleted": deleted_count, "total": len(lines_to_delete)}

        if skipped:
            message = _(
                "%(message)s %(skipped)s item(s) were skipped."
            ) % {"message": message, "skipped": len(skipped)}
            message = "%s\n%s" % (message, "\n".join(skipped[:3]))

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Delete Journal Items"),
                "message": message,
                "type": "warning" if skipped else "success",
                "sticky": bool(skipped),
            },
        }

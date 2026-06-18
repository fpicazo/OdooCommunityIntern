from calendar import monthrange
from collections import defaultdict
from datetime import date

from odoo import api, fields, models


class MatchContaIvaUtilityReportWizard(models.TransientModel):
    _name = "matchconta.iva.utility.report.wizard"
    _description = "MatchConta IVA Utility Report Wizard"

    month = fields.Selection(
        selection=[
            ("1", "January"),
            ("2", "February"),
            ("3", "March"),
            ("4", "April"),
            ("5", "May"),
            ("6", "June"),
            ("7", "July"),
            ("8", "August"),
            ("9", "September"),
            ("10", "October"),
            ("11", "November"),
            ("12", "December"),
        ],
        required=True,
        default=lambda self: str(fields.Date.context_today(self).month),
    )
    year = fields.Integer(
        required=True,
        default=lambda self: fields.Date.context_today(self).year,
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        readonly=True,
    )
    line_ids = fields.One2many(
        "matchconta.iva.utility.report.line",
        "wizard_id",
        string="Lines",
        readonly=True,
    )
    total_customer_payment = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_totals",
        readonly=True,
    )
    total_customer_iva = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_totals",
        readonly=True,
    )
    total_supplier_payment = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_totals",
        readonly=True,
    )
    total_supplier_iva = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_totals",
        readonly=True,
    )
    total_iva_difference = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_totals",
        readonly=True,
    )
    total_utility = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_totals",
        readonly=True,
    )

    @api.depends(
        "line_ids.customer_payment",
        "line_ids.customer_iva",
        "line_ids.supplier_payment",
        "line_ids.supplier_iva",
    )
    def _compute_totals(self):
        for wizard in self:
            wizard.total_customer_payment = sum(wizard.line_ids.mapped("customer_payment"))
            wizard.total_customer_iva = sum(wizard.line_ids.mapped("customer_iva"))
            wizard.total_supplier_payment = sum(wizard.line_ids.mapped("supplier_payment"))
            wizard.total_supplier_iva = sum(wizard.line_ids.mapped("supplier_iva"))
            wizard.total_iva_difference = (
                wizard.total_customer_iva - wizard.total_supplier_iva
            )
            wizard.total_utility = (
                wizard.total_customer_payment - wizard.total_supplier_payment
            )

    def _get_period_dates(self):
        self.ensure_one()
        month_number = int(self.month)
        last_day = monthrange(self.year, month_number)[1]
        return (
            date(self.year, month_number, 1),
            date(self.year, month_number, last_day),
        )

    def _get_invoice_totals_in_company_currency(self, move):
        total_amount = abs(move.amount_total_signed) or abs(move.amount_total)
        tax_amount = abs(move.amount_tax_signed) or abs(move.amount_tax)
        return total_amount, tax_amount

    def _get_report_lines_action(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "IVA Utility Report",
            "res_model": "matchconta.iva.utility.report.line",
            "view_mode": "list,form",
            "domain": [("wizard_id", "=", self.id)],
            "context": {
                "search_default_group_by_partner": 1,
                "default_wizard_id": self.id,
            },
            "target": "current",
        }

    @api.model
    def action_open_current_report(self):
        wizard = self.create({})
        return wizard.action_generate_report()

    def _get_reconciled_documents(self, payment):
        documents = defaultdict(
            lambda: {
                "move": self.env["account.move"],
                "payment_amount": 0.0,
                "iva_amount": 0.0,
            }
        )
        counterpart_lines = payment.move_id.line_ids.filtered(
            lambda line: line.account_id.account_type
            in ("asset_receivable", "liability_payable")
        )

        for line in counterpart_lines:
            for partial in line.matched_debit_ids:
                self._collect_partial_document(
                    documents,
                    partial.credit_move_id,
                    partial.amount,
                )
            for partial in line.matched_credit_ids:
                self._collect_partial_document(
                    documents,
                    partial.debit_move_id,
                    partial.amount,
                )

        currency = payment.company_id.currency_id
        for values in documents.values():
            move = values["move"]
            total_amount, tax_amount = self._get_invoice_totals_in_company_currency(move)
            if currency.is_zero(total_amount):
                continue
            ratio = min(values["payment_amount"] / total_amount, 1.0)
            values["iva_amount"] = currency.round(tax_amount * ratio)

        return list(documents.values())

    def _collect_partial_document(self, documents, counterpart_line, amount):
        move = counterpart_line.move_id
        if not move.is_invoice(include_receipts=True) or move.state != "posted":
            return

        document_bucket = documents[move.id]
        document_bucket["move"] = move
        document_bucket["payment_amount"] += abs(amount)

    def action_generate_report(self):
        self.ensure_one()
        date_from, date_to = self._get_period_dates()

        self.line_ids.unlink()

        payments = self.env["account.payment"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("date", ">=", date_from),
                ("date", "<=", date_to),
                ("move_id.state", "=", "posted"),
                ("state", "=", "posted"),
            ],
            order="date, id",
        )

        line_commands = []
        currency = self.company_id.currency_id

        for payment in payments:
            documents = self._get_reconciled_documents(payment)
            sale_documents = [
                document
                for document in documents
                if document["move"].is_sale_document(include_receipts=True)
            ]
            purchase_documents = [
                document
                for document in documents
                if document["move"].is_purchase_document(include_receipts=True)
            ]

            customer_payment = currency.round(
                sum(document["payment_amount"] for document in sale_documents)
            )
            customer_iva = currency.round(
                sum(document["iva_amount"] for document in sale_documents)
            )
            supplier_payment = currency.round(
                sum(document["payment_amount"] for document in purchase_documents)
            )
            supplier_iva = currency.round(
                sum(document["iva_amount"] for document in purchase_documents)
            )

            if (
                currency.is_zero(customer_payment)
                and currency.is_zero(supplier_payment)
                and currency.is_zero(customer_iva)
                and currency.is_zero(supplier_iva)
            ):
                continue

            invoice_names = ", ".join(
                sorted(
                    {
                        document["move"].name
                        for document in sale_documents + purchase_documents
                        if document["move"].name
                    }
                )
            )

            line_commands.append(
                (
                    0,
                    0,
                    {
                        "date": payment.date,
                        "payment_id": payment.id,
                        "partner_id": payment.partner_id.id,
                        "payment_reference": payment.payment_reference or payment.name,
                        "invoice_names": invoice_names,
                        "customer_payment": customer_payment,
                        "customer_iva": customer_iva,
                        "supplier_payment": supplier_payment,
                        "supplier_iva": supplier_iva,
                    },
                )
            )

        if line_commands:
            self.write({"line_ids": line_commands})

        return self._get_report_lines_action()


class MatchContaIvaUtilityReportLine(models.TransientModel):
    _name = "matchconta.iva.utility.report.line"
    _description = "MatchConta IVA Utility Report Line"
    _order = "date desc, id desc"

    wizard_id = fields.Many2one(
        "matchconta.iva.utility.report.wizard",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company",
        related="wizard_id.company_id",
        readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="wizard_id.currency_id",
        readonly=True,
    )
    report_company_id = fields.Many2one(
        "res.company",
        related="wizard_id.company_id",
        readonly=True,
    )
    report_month = fields.Selection(
        related="wizard_id.month",
        readonly=True,
    )
    report_year = fields.Integer(
        related="wizard_id.year",
        readonly=True,
    )
    date = fields.Date(required=True, readonly=True)
    payment_id = fields.Many2one("account.payment", readonly=True)
    partner_id = fields.Many2one("res.partner", readonly=True)
    payment_reference = fields.Char(readonly=True)
    invoice_names = fields.Char(readonly=True)
    customer_payment = fields.Monetary(
        currency_field="currency_id",
        readonly=True,
    )
    customer_iva = fields.Monetary(
        currency_field="currency_id",
        readonly=True,
    )
    supplier_payment = fields.Monetary(
        currency_field="currency_id",
        readonly=True,
    )
    supplier_iva = fields.Monetary(
        currency_field="currency_id",
        readonly=True,
    )
    iva_difference = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_derived_amounts",
        store=True,
        readonly=True,
    )
    utility = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_derived_amounts",
        store=True,
        readonly=True,
    )

    @api.depends(
        "customer_iva",
        "supplier_iva",
        "customer_payment",
        "supplier_payment",
    )
    def _compute_derived_amounts(self):
        for line in self:
            line.iva_difference = line.customer_iva - line.supplier_iva
            line.utility = line.customer_payment - line.supplier_payment

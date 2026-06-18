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
    total_paid_amount = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_totals",
        readonly=True,
    )
    total_taxable_base_16 = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_totals",
        readonly=True,
    )
    total_iva_16 = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_totals",
        readonly=True,
    )
    total_taxable_base_8 = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_totals",
        readonly=True,
    )
    total_iva_8 = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_totals",
        readonly=True,
    )
    total_exempt_amount = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_totals",
        readonly=True,
    )
    total_other_taxable_base = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_totals",
        readonly=True,
    )
    total_other_iva = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_totals",
        readonly=True,
    )
    total_iva_amount = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_totals",
        readonly=True,
    )

    @api.depends(
        "line_ids.paid_amount",
        "line_ids.taxable_base_16",
        "line_ids.iva_16",
        "line_ids.taxable_base_8",
        "line_ids.iva_8",
        "line_ids.exempt_amount",
        "line_ids.other_taxable_base",
        "line_ids.other_iva",
        "line_ids.total_iva",
    )
    def _compute_totals(self):
        for wizard in self:
            wizard.total_paid_amount = sum(wizard.line_ids.mapped("paid_amount"))
            wizard.total_taxable_base_16 = sum(
                wizard.line_ids.mapped("taxable_base_16")
            )
            wizard.total_iva_16 = sum(wizard.line_ids.mapped("iva_16"))
            wizard.total_taxable_base_8 = sum(
                wizard.line_ids.mapped("taxable_base_8")
            )
            wizard.total_iva_8 = sum(wizard.line_ids.mapped("iva_8"))
            wizard.total_exempt_amount = sum(wizard.line_ids.mapped("exempt_amount"))
            wizard.total_other_taxable_base = sum(
                wizard.line_ids.mapped("other_taxable_base")
            )
            wizard.total_other_iva = sum(wizard.line_ids.mapped("other_iva"))
            wizard.total_iva_amount = sum(wizard.line_ids.mapped("total_iva"))

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

    def _is_iva_tax(self, tax):
        if tax.amount_type != "percent":
            return False

        tax_names = " ".join(
            filter(
                None,
                [tax.name, tax.tax_group_id.name if tax.tax_group_id else None],
            )
        ).lower()
        return "iva" in tax_names or "vat" in tax_names

    def _get_rate_bucket(self, rate):
        rounded_rate = round(abs(rate), 2)
        if abs(rounded_rate - 16.0) < 0.01:
            return "16"
        if abs(rounded_rate - 8.0) < 0.01:
            return "8"
        if abs(rounded_rate) < 0.01:
            return "exempt"
        return "other"

    def _get_third_party_type(self, partner):
        country_code = partner.country_id.code if partner.country_id else "MX"
        return "04" if country_code == "MX" else "05"

    def _get_operation_type(self):
        # Default DIOT operation code for general supplier purchases.
        return "85"

    def _prepare_document_breakdown(self, move, payment_amount):
        currency = move.company_id.currency_id
        total_amount, _tax_amount = self._get_invoice_totals_in_company_currency(move)
        breakdown = {
            "taxable_base_16": 0.0,
            "iva_16": 0.0,
            "taxable_base_8": 0.0,
            "iva_8": 0.0,
            "exempt_amount": 0.0,
            "other_taxable_base": 0.0,
            "other_iva": 0.0,
        }

        if currency.is_zero(total_amount):
            return breakdown

        ratio = min(payment_amount / total_amount, 1.0)

        for invoice_line in move.invoice_line_ids.filtered(lambda line: not line.display_type):
            base_amount = abs(invoice_line.balance)
            if currency.is_zero(base_amount):
                continue

            proportional_base = currency.round(base_amount * ratio)
            iva_taxes = invoice_line.tax_ids.filtered(self._is_iva_tax)
            if not iva_taxes:
                breakdown["exempt_amount"] += proportional_base
                continue

            main_tax = iva_taxes.sorted(key=lambda tax: abs(tax.amount), reverse=True)[0]
            bucket = self._get_rate_bucket(main_tax.amount)
            if bucket == "16":
                breakdown["taxable_base_16"] += proportional_base
            elif bucket == "8":
                breakdown["taxable_base_8"] += proportional_base
            elif bucket == "exempt":
                breakdown["exempt_amount"] += proportional_base
            else:
                breakdown["other_taxable_base"] += proportional_base

        for tax_line in move.line_ids.filtered(
            lambda line: line.tax_line_id and self._is_iva_tax(line.tax_line_id)
        ):
            proportional_tax = currency.round(abs(tax_line.balance) * ratio)
            bucket = self._get_rate_bucket(tax_line.tax_line_id.amount)
            if bucket == "16":
                breakdown["iva_16"] += proportional_tax
            elif bucket == "8":
                breakdown["iva_8"] += proportional_tax
            elif bucket == "other":
                breakdown["other_iva"] += proportional_tax

        return breakdown

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
                ("state", "in", ("in_process", "paid")),
            ],
            order="date, id",
        )

        currency = self.company_id.currency_id
        partner_totals = {}

        for payment in payments:
            documents = self._get_reconciled_documents(payment)
            purchase_documents = [
                document
                for document in documents
                if document["move"].is_purchase_document(include_receipts=True)
            ]

            for document in purchase_documents:
                move = document["move"]
                partner = (move.partner_id or payment.partner_id).commercial_partner_id
                partner_key = partner.id or "no_partner"
                sign = -1.0 if move.move_type in ("in_refund", "out_refund") else 1.0
                breakdown = self._prepare_document_breakdown(
                    move,
                    document["payment_amount"],
                )

                if partner_key not in partner_totals:
                    partner_totals[partner_key] = {
                        "partner": partner,
                        "third_party_type": self._get_third_party_type(partner),
                        "operation_type": self._get_operation_type(),
                        "rfc": partner.vat or "",
                        "country_code": partner.country_id.code or "",
                        "document_names": set(),
                        "payment_references": set(),
                        "paid_amount": 0.0,
                        "taxable_base_16": 0.0,
                        "iva_16": 0.0,
                        "taxable_base_8": 0.0,
                        "iva_8": 0.0,
                        "exempt_amount": 0.0,
                        "other_taxable_base": 0.0,
                        "other_iva": 0.0,
                    }

                totals = partner_totals[partner_key]
                totals["paid_amount"] += sign * currency.round(document["payment_amount"])
                totals["taxable_base_16"] += sign * breakdown["taxable_base_16"]
                totals["iva_16"] += sign * breakdown["iva_16"]
                totals["taxable_base_8"] += sign * breakdown["taxable_base_8"]
                totals["iva_8"] += sign * breakdown["iva_8"]
                totals["exempt_amount"] += sign * breakdown["exempt_amount"]
                totals["other_taxable_base"] += sign * breakdown["other_taxable_base"]
                totals["other_iva"] += sign * breakdown["other_iva"]

                if move.name:
                    totals["document_names"].add(move.name)
                payment_reference = payment.payment_reference or payment.name
                if payment_reference:
                    totals["payment_references"].add(payment_reference)

        line_commands = []
        for values in sorted(
            partner_totals.values(),
            key=lambda item: item["partner"].display_name or "",
        ):
            if (
                currency.is_zero(values["paid_amount"])
                and currency.is_zero(values["taxable_base_16"])
                and currency.is_zero(values["iva_16"])
                and currency.is_zero(values["taxable_base_8"])
                and currency.is_zero(values["iva_8"])
                and currency.is_zero(values["exempt_amount"])
                and currency.is_zero(values["other_taxable_base"])
                and currency.is_zero(values["other_iva"])
            ):
                continue

            line_commands.append(
                (
                    0,
                    0,
                    {
                        "partner_id": values["partner"].id,
                        "third_party_type": values["third_party_type"],
                        "operation_type": values["operation_type"],
                        "rfc": values["rfc"],
                        "country_code": values["country_code"],
                        "payment_references": ", ".join(sorted(values["payment_references"])),
                        "document_names": ", ".join(sorted(values["document_names"])),
                        "paid_amount": currency.round(values["paid_amount"]),
                        "taxable_base_16": currency.round(values["taxable_base_16"]),
                        "iva_16": currency.round(values["iva_16"]),
                        "taxable_base_8": currency.round(values["taxable_base_8"]),
                        "iva_8": currency.round(values["iva_8"]),
                        "exempt_amount": currency.round(values["exempt_amount"]),
                        "other_taxable_base": currency.round(values["other_taxable_base"]),
                        "other_iva": currency.round(values["other_iva"]),
                    },
                )
            )

        if line_commands:
            self.write({"line_ids": line_commands})

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "current",
        }


class MatchContaIvaUtilityReportLine(models.TransientModel):
    _name = "matchconta.iva.utility.report.line"
    _description = "MatchConta IVA Utility Report Line"
    _order = "partner_id, id"

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
    partner_id = fields.Many2one("res.partner", readonly=True)
    third_party_type = fields.Char(readonly=True)
    operation_type = fields.Char(readonly=True)
    rfc = fields.Char(readonly=True)
    country_code = fields.Char(readonly=True)
    payment_references = fields.Char(readonly=True)
    document_names = fields.Char(readonly=True)
    paid_amount = fields.Monetary(
        currency_field="currency_id",
        readonly=True,
    )
    taxable_base_16 = fields.Monetary(
        currency_field="currency_id",
        readonly=True,
    )
    iva_16 = fields.Monetary(
        currency_field="currency_id",
        readonly=True,
    )
    taxable_base_8 = fields.Monetary(
        currency_field="currency_id",
        readonly=True,
    )
    iva_8 = fields.Monetary(
        currency_field="currency_id",
        readonly=True,
    )
    exempt_amount = fields.Monetary(
        currency_field="currency_id",
        readonly=True,
    )
    other_taxable_base = fields.Monetary(
        currency_field="currency_id",
        readonly=True,
    )
    other_iva = fields.Monetary(
        currency_field="currency_id",
        readonly=True,
    )
    total_iva = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_total_iva",
        store=True,
        readonly=True,
    )

    @api.depends("iva_16", "iva_8", "other_iva")
    def _compute_total_iva(self):
        for line in self:
            line.total_iva = line.iva_16 + line.iva_8 + line.other_iva

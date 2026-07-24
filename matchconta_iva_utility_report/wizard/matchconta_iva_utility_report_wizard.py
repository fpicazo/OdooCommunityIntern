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
    total_customer_payment_with_tax_excl_iva = fields.Monetary(
        string="Payments Received with Tax (Excl. IVA)",
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
    period_iva_no_acreditable = fields.Monetary(
        string="Period Non-creditable IVA",
        currency_field="currency_id",
        compute="_compute_period_iva_no_acreditable",
        readonly=True,
    )
    period_depreciation = fields.Monetary(
        string="Period Depreciation",
        currency_field="currency_id",
        compute="_compute_period_depreciation",
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

    def name_get(self):
        month_labels = dict(self._fields["month"].selection)
        result = []
        for wizard in self:
            month_label = month_labels.get(wizard.month, "")
            label = f"IVA Utility Report - {month_label} {wizard.year}".strip()
            result.append((wizard.id, label))
        return result

    @api.depends(
        "line_ids.customer_payment",
        "line_ids.customer_iva",
        "line_ids.customer_payment_with_tax_excl_iva",
        "line_ids.supplier_payment",
        "line_ids.supplier_iva",
        "line_ids.payroll_amount",
        "line_ids.depreciation_amount",
    )
    def _compute_totals(self):
        for wizard in self:
            wizard.total_customer_payment = sum(wizard.line_ids.mapped("customer_payment"))
            wizard.total_customer_iva = sum(wizard.line_ids.mapped("customer_iva"))
            wizard.total_customer_payment_with_tax_excl_iva = sum(
                wizard.line_ids.mapped("customer_payment_with_tax_excl_iva")
            )
            wizard.total_supplier_payment = sum(wizard.line_ids.mapped("supplier_payment"))
            wizard.total_supplier_iva = sum(wizard.line_ids.mapped("supplier_iva"))
            wizard.total_iva_difference = (
                wizard.total_customer_iva - wizard.total_supplier_iva
            )
            wizard.total_utility = (
                (wizard.total_customer_payment - wizard.total_customer_iva)
                - (wizard.total_supplier_payment - wizard.total_supplier_iva)
                - sum(wizard.line_ids.mapped("payroll_amount"))
                - sum(wizard.line_ids.mapped("depreciation_amount"))
            )

    @api.depends("company_id", "month", "year")
    def _compute_period_iva_no_acreditable(self):
        period_keys = {
            (wizard.company_id.id, str(wizard.month).zfill(2), wizard.year)
            for wizard in self
            if wizard.company_id and wizard.month and wizard.year
        }
        amount_map = self.env[
            "matchconta.declared.amounts"
        ]._get_iva_no_acreditable_amount_map(period_keys)
        for wizard in self:
            wizard.period_iva_no_acreditable = amount_map.get(
                (wizard.company_id.id, str(wizard.month).zfill(2), wizard.year),
                0.0,
            )

    @api.depends("company_id", "month", "year")
    def _compute_period_depreciation(self):
        for wizard in self:
            wizard.period_depreciation = 0.0
            if not wizard.company_id or not wizard.month or not wizard.year:
                continue
            date_from, date_to = wizard._get_period_dates()
            entries = wizard._get_depreciation_entries(date_from, date_to)
            wizard.period_depreciation = sum(entry["amount"] for entry in entries)

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
                "search_default_group_by_payment_month": 1,
                "default_wizard_id": self.id,
            },
            "target": "current",
        }

    def _open_debug_popup(self, debug_lines):
        debug_wizard = self.env["matchconta.iva.utility.report.debug"].create(
            {
                "wizard_id": self.id,
                "message": "\n".join(debug_lines),
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": "IVA Utility Report Debug",
            "res_model": "matchconta.iva.utility.report.debug",
            "view_mode": "form",
            "res_id": debug_wizard.id,
            "target": "new",
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
        payment_lines = payment.move_id.line_ids
        partials = payment_lines.matched_debit_ids | payment_lines.matched_credit_ids
        counterpart_lines = (partials.debit_move_id | partials.credit_move_id) - payment_lines

        for counterpart_line in counterpart_lines:
            related_partials = (counterpart_line.matched_debit_ids | counterpart_line.matched_credit_ids).filtered(
                lambda partial: partial.debit_move_id in payment_lines
                or partial.credit_move_id in payment_lines
            )
            paid_amount = sum(related_partials.mapped("amount"))
            if not paid_amount:
                continue
            self._collect_partial_document(
                documents,
                counterpart_line,
                paid_amount,
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

    def _get_iva_no_acreditable_entries(self, date_from, date_to):
        self.ensure_one()
        currency = self.company_id.currency_id
        move_lines = self.env["account.move.line"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("date", ">=", date_from),
                ("date", "<=", date_to),
                ("parent_state", "=", "posted"),
                ("move_id.move_type", "=", "entry"),
                "|",
                ("account_id.name", "ilike", "IVA no acreditable"),
                ("name", "ilike", "IVA no acreditable"),
            ],
            order="date, move_id, id",
        )

        entries = defaultdict(
            lambda: {
                "move": self.env["account.move"],
                "partner": self.env["res.partner"],
                "date": False,
                "amount": 0.0,
            }
        )

        for move_line in move_lines:
            bucket = entries[move_line.move_id.id]
            bucket["move"] = move_line.move_id
            bucket["partner"] = move_line.partner_id or move_line.move_id.partner_id
            bucket["date"] = move_line.date
            bucket["amount"] += move_line.debit - move_line.credit

        result = []
        for values in entries.values():
            amount = currency.round(values["amount"])
            if currency.is_zero(amount):
                continue
            values["amount"] = amount
            result.append(values)

        return sorted(
            result,
            key=lambda values: (
                values["date"] or date.min,
                values["move"].id,
            ),
        )

    def _get_depreciation_entries(self, date_from, date_to):
        self.ensure_one()
        currency = self.company_id.currency_id
        move_lines = self.env["account.move.line"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("date", ">=", date_from),
                ("date", "<=", date_to),
                ("parent_state", "=", "posted"),
                ("move_id.move_type", "=", "entry"),
                ("debit", ">", 0),
                ("account_id.name", "ilike", "Depreci"),
                ("account_id.name", "not ilike", "acumul"),
            ],
            order="date, move_id, id",
        )

        entries = defaultdict(
            lambda: {
                "move": self.env["account.move"],
                "partner": self.env["res.partner"],
                "date": False,
                "amount": 0.0,
            }
        )

        for move_line in move_lines:
            bucket = entries[move_line.move_id.id]
            bucket["move"] = move_line.move_id
            bucket["partner"] = move_line.partner_id or move_line.move_id.partner_id
            bucket["date"] = move_line.date
            bucket["amount"] += move_line.debit

        result = []
        for values in entries.values():
            amount = currency.round(values["amount"])
            if currency.is_zero(amount):
                continue
            values["amount"] = amount
            result.append(values)

        return sorted(
            result,
            key=lambda values: (
                values["date"] or date.min,
                values["move"].id,
            ),
        )

    def action_generate_report(self):
        self.ensure_one()
        date_from, date_to = self._get_period_dates()

        self.line_ids.unlink()

        debug_lines = [
            f"Company: {self.company_id.display_name}",
            f"Period: {date_from} to {date_to}",
            "Payment domain:",
            "- company_id = selected company",
            "- date within selected period",
            "- move_id.state = posted",
            "- payment.state in paid, posted, in_process",
            "",
        ]

        Payment = self.env["account.payment"]
        payments_same_company = Payment.search([
            ("company_id", "=", self.company_id.id),
        ])
        payments_same_company_period = Payment.search([
            ("company_id", "=", self.company_id.id),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
        ])
        payments_same_company_posted = Payment.search([
            ("company_id", "=", self.company_id.id),
            ("state", "in", ("paid", "posted", "in_process")),
        ])
        payments_same_period_any_company = Payment.search([
            ("date", ">=", date_from),
            ("date", "<=", date_to),
            ("state", "in", ("paid", "posted", "in_process")),
        ])
        payments_with_posted_moves = Payment.search([
            ("move_id.state", "=", "posted"),
            ("state", "in", ("paid", "posted", "in_process")),
        ])

        debug_lines.extend(
            [
                "Stepwise counts:",
                f"- Payments for selected company: {len(payments_same_company)}",
                f"- Payments for selected company in period: {len(payments_same_company_period)}",
                f"- Posted payments for selected company: {len(payments_same_company_posted)}",
                f"- Posted payments in period for any company: {len(payments_same_period_any_company)}",
                f"- Posted payments with posted journal entry: {len(payments_with_posted_moves)}",
                "",
            ]
        )

        if payments_same_company:
            company_dates = payments_same_company.mapped("date")
            company_dates = [payment_date for payment_date in company_dates if payment_date]
            if company_dates:
                debug_lines.append(
                    f"Selected company payment date range: {min(company_dates)} to {max(company_dates)}"
                )
            company_states = sorted(set(payments_same_company.mapped("state")))
            debug_lines.append(
                f"Selected company payment states: {', '.join(company_states)}"
            )
        else:
            debug_lines.append("Selected company has no account.payment records at all.")

        if payments_same_period_any_company:
            sample_companies = ", ".join(
                sorted(
                    set(
                        payments_same_period_any_company[:10]
                        .mapped("company_id.display_name")
                    )
                )
            )
            debug_lines.append(
                f"Companies with posted payments in period: {sample_companies}"
            )
        debug_lines.append("")

        payments = Payment.search(
            [
                ("company_id", "=", self.company_id.id),
                ("date", ">=", date_from),
                ("date", "<=", date_to),
                ("move_id.state", "=", "posted"),
                ("state", "in", ("paid", "posted", "in_process")),
            ],
            order="date, id",
        )

        debug_lines.append(f"Payments found: {len(payments)}")
        if payments:
            sample_payments = ", ".join(payments[:10].mapped("display_name"))
            debug_lines.append(f"Sample payments: {sample_payments}")
        else:
            debug_lines.append("No payments matched the search domain.")

        line_commands = []
        currency = self.company_id.currency_id
        reconciled_document_count = 0
        lines_created = 0
        skipped_without_documents = 0
        skipped_zero_totals = 0

        for payment in payments:
            documents = self._get_reconciled_documents(payment)
            reconciled_document_count += len(documents)
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

            if not documents:
                skipped_without_documents += 1
                continue

            customer_payment = currency.round(
                sum(document["payment_amount"] for document in sale_documents)
            )
            customer_iva = currency.round(
                sum(document["iva_amount"] for document in sale_documents)
            )
            customer_payment_with_tax_excl_iva = currency.round(
                sum(
                    document["payment_amount"] - document["iva_amount"]
                    for document in sale_documents
                    if not currency.is_zero(document["iva_amount"])
                )
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
                skipped_zero_totals += 1
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
                        "customer_payment_with_tax_excl_iva": (
                            customer_payment_with_tax_excl_iva
                        ),
                        "supplier_payment": supplier_payment,
                        "supplier_iva": supplier_iva,
                    },
                )
            )
            lines_created += 1

        iva_no_acreditable_entries = self._get_iva_no_acreditable_entries(
            date_from,
            date_to,
        )
        debug_lines.append(
            f"IVA no acreditable journal entries found: {len(iva_no_acreditable_entries)}"
        )
        for entry in iva_no_acreditable_entries:
            move = entry["move"]
            line_commands.append(
                (
                    0,
                    0,
                    {
                        "date": entry["date"],
                        "partner_id": entry["partner"].id,
                        "payment_reference": move.ref or "IVA no acreditable",
                        "invoice_names": move.name,
                        "iva_no_acreditable": entry["amount"],
                    },
                )
            )
            lines_created += 1

        depreciation_entries = self._get_depreciation_entries(
            date_from,
            date_to,
        )
        debug_lines.append(
            f"Depreciation journal entries found: {len(depreciation_entries)}"
        )
        for entry in depreciation_entries:
            move = entry["move"]
            line_commands.append(
                (
                    0,
                    0,
                    {
                        "date": entry["date"],
                        "partner_id": entry["partner"].id,
                        "payment_reference": move.ref or "Depreciation",
                        "invoice_names": move.name,
                        "depreciation_amount": entry["amount"],
                    },
                )
            )
            lines_created += 1

        declared_amount = self.env["matchconta.declared.amounts"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("month", "=", str(self.month).zfill(2)),
                ("year", "=", self.year),
            ],
            limit=1,
        )
        payroll_amount = currency.round(declared_amount.nomina_declarado)
        if not currency.is_zero(payroll_amount):
            line_commands.append(
                (
                    0,
                    0,
                    {
                        "date": date_to,
                        "payment_reference": "Payroll",
                        "payroll_amount": payroll_amount,
                    },
                )
            )
            lines_created += 1

        if line_commands:
            self.write({"line_ids": line_commands})
            return self._get_report_lines_action()

        debug_lines.extend(
            [
                f"Reconciled documents found: {reconciled_document_count}",
                f"Report lines created: {lines_created}",
                f"Payments skipped without reconciled documents: {skipped_without_documents}",
                f"Payments skipped because computed totals were zero: {skipped_zero_totals}",
            ]
        )
        if payments:
            first_payment = payments[0]
            first_documents = self._get_reconciled_documents(first_payment)
            debug_lines.append("")
            debug_lines.append(f"First payment checked: {first_payment.display_name}")
            debug_lines.append(
                f"Documents linked to first payment: {len(first_documents)}"
            )
            if first_documents:
                debug_lines.extend(
                    [
                        f"- {document['move'].name or document['move'].id}: {document['move'].move_type}, paid={document['payment_amount']}, iva={document['iva_amount']}"
                        for document in first_documents[:10]
                    ]
                )

        return self._open_debug_popup(debug_lines)


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
    report_period_label = fields.Char(
        compute="_compute_report_period_label",
        readonly=True,
    )
    transaction_type = fields.Selection(
        selection=[
            ("income", "Income"),
            ("expense", "Expense"),
            ("mixed", "Mixed"),
            ("adjustment", "Adjustment"),
        ],
        compute="_compute_transaction_type",
        store=True,
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
    customer_payment_with_tax_excl_iva = fields.Monetary(
        string="Payments Received with Tax (Excl. IVA)",
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
    declared_ingreso = fields.Monetary(
        string="Declared Income",
        currency_field="currency_id",
        compute="_compute_declared_amounts",
        store=True,
        group_operator="max",
        readonly=True,
    )
    declared_egreso = fields.Monetary(
        string="Declared Expense",
        currency_field="currency_id",
        compute="_compute_declared_amounts",
        store=True,
        group_operator="max",
        readonly=True,
    )
    declared_isr = fields.Monetary(
        string="Declared ISR",
        currency_field="currency_id",
        compute="_compute_declared_amounts",
        store=True,
        group_operator="max",
        readonly=True,
    )
    declared_iva_cobrado = fields.Monetary(
        string="Declared IVA Collected",
        currency_field="currency_id",
        compute="_compute_declared_amounts",
        store=True,
        group_operator="max",
        readonly=True,
    )
    declared_iva_pagado = fields.Monetary(
        string="Declared IVA Paid",
        currency_field="currency_id",
        compute="_compute_declared_amounts",
        store=True,
        group_operator="max",
        readonly=True,
    )
    declared_iva_pagable = fields.Monetary(
        string="Declared IVA Payable",
        currency_field="currency_id",
        compute="_compute_declared_amounts",
        store=True,
        group_operator="max",
        readonly=True,
    )
    iva_no_acreditable = fields.Monetary(
        string="IVA No Acreditable",
        currency_field="currency_id",
        readonly=True,
    )
    depreciation_amount = fields.Monetary(
        string="Depreciation",
        currency_field="currency_id",
        readonly=True,
    )
    payroll_amount = fields.Monetary(
        string="Payroll",
        currency_field="currency_id",
        readonly=True,
    )
    period_iva_no_acreditable = fields.Monetary(
        string="Period Non-creditable IVA",
        currency_field="currency_id",
        related="wizard_id.period_iva_no_acreditable",
        readonly=True,
    )
    period_depreciation = fields.Monetary(
        string="Period Depreciation",
        currency_field="currency_id",
        related="wizard_id.period_depreciation",
        readonly=True,
    )
    declared_nomina = fields.Monetary(
        string="Declared Payroll",
        currency_field="currency_id",
        compute="_compute_declared_amounts",
        store=True,
        group_operator="max",
        readonly=True,
    )
    declared_isr_nomina_pagado = fields.Monetary(
        string="Declared Payroll ISR Paid",
        currency_field="currency_id",
        compute="_compute_declared_amounts",
        store=True,
        group_operator="max",
        readonly=True,
    )
    declared_perdidas_fiscales_aplicadas_periodo = fields.Monetary(
        string="Declared Prior-Year Tax Losses Applied",
        currency_field="currency_id",
        compute="_compute_declared_amounts",
        store=True,
        group_operator="max",
        readonly=True,
    )

    @api.depends(
        "customer_iva",
        "supplier_iva",
        "customer_payment",
        "supplier_payment",
        "payroll_amount",
        "depreciation_amount",
    )
    def _compute_derived_amounts(self):
        for line in self:
            line.iva_difference = line.customer_iva - line.supplier_iva
            line.utility = (
                (line.customer_payment - line.customer_iva)
                - (line.supplier_payment - line.supplier_iva)
                - line.payroll_amount
                - line.depreciation_amount
            )

    @api.depends("report_month", "report_year")
    def _compute_report_period_label(self):
        month_labels = dict(self.env["matchconta.iva.utility.report.wizard"]._fields["month"].selection)
        for line in self:
            month_label = month_labels.get(line.report_month, "")
            year_label = str(line.report_year) if line.report_year else ""
            line.report_period_label = " ".join(filter(None, [month_label, year_label]))

    @api.depends(
        "customer_payment",
        "supplier_payment",
        "iva_no_acreditable",
        "payroll_amount",
        "depreciation_amount",
    )
    def _compute_transaction_type(self):
        for line in self:
            has_customer = not line.currency_id.is_zero(line.customer_payment)
            has_supplier = not line.currency_id.is_zero(line.supplier_payment)
            has_adjustment = (
                not line.currency_id.is_zero(line.iva_no_acreditable)
                or not line.currency_id.is_zero(line.payroll_amount)
            )
            has_depreciation = not line.currency_id.is_zero(line.depreciation_amount)
            if has_customer and has_supplier:
                line.transaction_type = "mixed"
            elif has_customer:
                line.transaction_type = "income"
            elif has_adjustment or has_depreciation:
                line.transaction_type = "adjustment"
            else:
                line.transaction_type = "expense"

    @api.depends("report_company_id", "report_month", "report_year")
    def _compute_declared_amounts(self):
        key_by_line = {}
        company_ids = set()
        years = set()
        months = set()

        for line in self:
            if not line.report_company_id or not line.report_month or not line.report_year:
                continue
            month_key = str(line.report_month).zfill(2)
            key = (line.report_company_id.id, month_key, line.report_year)
            key_by_line[line.id] = key
            company_ids.add(line.report_company_id.id)
            years.add(line.report_year)
            months.add(month_key)

        declared_map = {}
        if company_ids and years and months:
            declared_records = self.env["matchconta.declared.amounts"].search(
                [
                    ("company_id", "in", list(company_ids)),
                    ("year", "in", list(years)),
                    ("month", "in", list(months)),
                ]
            )
            declared_map = {
                (rec.company_id.id, rec.month, rec.year): rec
                for rec in declared_records
            }

        for line in self:
            declared = declared_map.get(key_by_line.get(line.id))
            line.declared_ingreso = declared.ingreso_declarado if declared else 0.0
            line.declared_egreso = declared.egreso_declarado if declared else 0.0
            line.declared_isr = declared.isr_declarado if declared else 0.0
            line.declared_iva_cobrado = declared.iva_cobrado_declarado if declared else 0.0
            line.declared_iva_pagado = declared.iva_pagado if declared else 0.0
            line.declared_iva_pagable = declared.iva_pagable_declarado if declared else 0.0
            line.declared_nomina = declared.nomina_declarado if declared else 0.0
            line.declared_isr_nomina_pagado = declared.isr_nomina_pagado if declared else 0.0
            line.declared_perdidas_fiscales_aplicadas_periodo = (
                declared.perdidas_fiscales_aplicadas_periodo if declared else 0.0
            )


class MatchContaIvaUtilityReportDebug(models.TransientModel):
    _name = "matchconta.iva.utility.report.debug"
    _description = "MatchConta IVA Utility Report Debug"

    wizard_id = fields.Many2one(
        "matchconta.iva.utility.report.wizard",
        required=True,
        ondelete="cascade",
    )
    message = fields.Text(readonly=True)

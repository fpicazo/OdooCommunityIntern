from calendar import monthrange
from datetime import date

from odoo import api, fields, models


class MatchContaDeclaredAmounts(models.Model):
    _name = "matchconta.declared.amounts"
    _description = "Declared Amounts for Tax Reconciliation"
    _order = "year desc, month desc"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    month = fields.Selection(
        selection=[
            ("01", "January"),
            ("02", "February"),
            ("03", "March"),
            ("04", "April"),
            ("05", "May"),
            ("06", "June"),
            ("07", "July"),
            ("08", "August"),
            ("09", "September"),
            ("10", "October"),
            ("11", "November"),
            ("12", "December"),
        ],
        string="Month",
        required=True,
    )
    year = fields.Integer(
        string="Year",
        required=True,
        default=lambda self: fields.Date.today().year,
    )

    # Declared amounts fields
    ingreso_declarado = fields.Float(
        string="Declared Income",
        help="Total declared income for the period",
    )
    egreso_declarado = fields.Float(
        string="Declared Expenses",
        help="Total declared expenses for the period",
    )
    isr_declarado = fields.Float(
        string="Declared ISR",
        help="Declared Income Tax (ISR) for the period",
    )
    iva_cobrado_declarado = fields.Float(
        string="Declared IVA Collected",
        help="Declared IVA collected from customers",
    )
    iva_pagado = fields.Float(
        string="Paid IVA",
        help="IVA paid to suppliers",
    )
    iva_pagable_declarado = fields.Float(
        string="Declared Payable IVA",
        help="Declared payable IVA for the period",
    )
    nomina_declarado = fields.Float(
        string="Declared Payroll",
        help="Declared payroll expenses for the period",
    )
    isr_nomina_pagado = fields.Float(
        string="Paid Payroll ISR",
        help="ISR withheld and paid from payroll",
    )
    iva_no_acreditable = fields.Float(
        string="Non-creditable IVA",
        compute="_compute_iva_no_acreditable",
        readonly=True,
        help="Posted IVA no acreditable journal items for the selected period.",
    )

    _sql_constraints = [
        (
            "unique_period",
            "unique(company_id, month, year)",
            "A declared amounts record already exists for this company and period.",
        ),
    ]

    @api.depends("month", "year")
    def name_get(self):
        result = []
        for record in self:
            month_names = dict(self._fields["month"].selection)
            month_name = month_names.get(record.month, "Unknown")
            name = f"{month_name} {record.year}"
            result.append((record.id, name))
        return result

    @api.model
    def _get_period_date_range(self, month, year):
        last_day = monthrange(year, int(month))[1]
        return date(year, int(month), 1), date(year, int(month), last_day)

    @api.model
    def _get_iva_no_acreditable_amount_map(self, period_keys):
        currency_by_company = {
            company.id: company.currency_id
            for company in self.env["res.company"].browse(
                list({company_id for company_id, _, _ in period_keys if company_id})
            )
        }
        amount_map = {}
        move_line_model = self.env["account.move.line"]

        for company_id, month, year in period_keys:
            if not company_id or not month or not year:
                continue
            date_from, date_to = self._get_period_date_range(month, year)
            totals = move_line_model.read_group(
                [
                    ("company_id", "=", company_id),
                    ("date", ">=", date_from),
                    ("date", "<=", date_to),
                    ("parent_state", "=", "posted"),
                    "|",
                    ("account_id.name", "ilike", "IVA no acreditable"),
                    ("name", "ilike", "IVA no acreditable"),
                ],
                ["debit:sum", "credit:sum"],
                [],
            )
            currency = currency_by_company.get(company_id)
            amount = 0.0
            if totals:
                amount = totals[0].get("debit", 0.0) - totals[0].get("credit", 0.0)
                if currency:
                    amount = currency.round(amount)
            amount_map[(company_id, month, year)] = amount

        return amount_map

    @api.depends("company_id", "month", "year")
    def _compute_iva_no_acreditable(self):
        period_keys = {
            (record.company_id.id, record.month, record.year)
            for record in self
            if record.company_id and record.month and record.year
        }
        amount_map = self._get_iva_no_acreditable_amount_map(period_keys)

        for record in self:
            record.iva_no_acreditable = amount_map.get(
                (record.company_id.id, record.month, record.year),
                0.0,
            )

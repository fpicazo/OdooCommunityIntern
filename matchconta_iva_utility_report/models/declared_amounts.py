from odoo import models, fields, api


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

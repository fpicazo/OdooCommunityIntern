from odoo import models, fields

class BillReceive(models.Model):
    _inherit = 'account.move'

    folio_fiscal = fields.Char(string="Folio Fiscal")
    payment_exchange_rate = fields.Float(string="Payment Exchange Rate", digits=(12, 6))

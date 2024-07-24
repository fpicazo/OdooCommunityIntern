from . import bill_receive
from odoo import models, fields

class BillReceive(models.Model):
    _inherit = 'account.move'

    folio_fiscal = fields.Char(string="Folio Fiscal")

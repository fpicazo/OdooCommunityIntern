# invoice_button_draft/models/product_template.py
from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    sat_unit_code = fields.Char(string='Sat Unit Code')
    sat_code_product = fields.Char(string='Sat Code Product')

from odoo import models, fields

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    solucion = fields.Selection([
        ('zoho', 'Zoho'),
        ('odoo', 'Odoo'),
        ('desarollo', 'Desarollo'),
    ], string='Solución')

    tipo_de_proyecto = fields.Selection([
        ('proyecto', 'Proyecto'),
        ('horas', 'Horas'),
        ('licencias', 'Licencias'),
        ('proyecto_puntual', 'Proyecto Puntual'),
    ], string='Tipo de Proyecto')

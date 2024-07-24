from odoo import models, fields

class Project(models.Model):
    _inherit = 'project.project'

    solucion_elegida = fields.Selection([
        ('zoho', 'Zoho'),
        ('odoo', 'Odoo'),
        ('desarollo', 'Desarollo'),
    ], string='Solución Elegida')

    tipo_de_proyecto = fields.Selection([
        ('interno', 'Interno'),
        ('externo', 'Externo'),
    ], string='Tipo de Proyecto')

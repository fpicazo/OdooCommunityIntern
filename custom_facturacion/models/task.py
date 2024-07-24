from odoo import models, fields

class ProjectTask(models.Model):
    _inherit = 'project.task'

    tipo_de_tarea = fields.Selection([
        ('desarollo', 'Desarollo'),
        ('configuracion', 'Configuracion'),
        ('junta_interna', 'Junta Interna'),
        ('junta_cliente', 'Junta Cliente'),
        ('otro', 'Otro'),
    ], string='Tipo de Tarea')

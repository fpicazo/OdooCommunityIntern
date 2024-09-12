from odoo import models, fields

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    fecha_entrada = fields.Date(string='Fecha de Entrada220')
    fecha_salida = fields.Date(string='Fecha de Salida')
    sueldo_diario = fields.Float(string='Sueldo Diario')
    dias_de_vacaciones_por_ano = fields.Integer(string='Días de Vacaciones por Año')

# invoice_button_draft/models/res_partner.py
from odoo import models, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'

    regimen_fiscal = fields.Selection([
        ('601', 'General de Ley de Personas Morales'),
        ('603', 'Personas morales con fines no lucrativos'),
        ('605', 'Sueldos y Salarios e Ingresos Asimilados a Salarios'),
        ('606', 'Arrendamiento'),
        ('607', 'Régimen de enajenación o adquisición de bienes'),
        ('608', 'Demás ingresos'),
        ('609', 'Consolidación'),
        ('610', 'Residentes en el extranjero sin establecimiento permanente en México'),
        ('611', 'Ingresos por Dividendos (socios y accionistas'),
        ('612', 'Personas físicas con actividades empresariales y profesionales'),
        ('614', 'Ingresos por intereses'),
        ('615', 'Régimen de los ingresos por obtención de premios'),
        ('616', 'Sin obligaciones fiscales'),
        ('620', 'Sociedades Cooperativas de Producción que optan por diferir sus ingresos'),
        ('621', 'Incorporación fiscal'),
        ('622', 'Actividades Agrícolas, Ganaderas, Silvícolas y Pesqueras'),
        ('623', 'Opcional para grupos de sociedades'),
        ('624', 'Coordinados'),
        ('625', 'Régimen de las Actividades Empresariales con ingresos a través de Plataformas Tecnológicas'),
        ('626', 'Régimen Simplificado de Confianza - RESICO'),
        ('628', 'Hidrocarburos'),
        ('629', 'De los Regímenes Fiscales Preferentes y de las Empresas Multinacionales'),
        ('630', 'Enajenación de acciones en bolsa de valores')
    ], string='Regimen Fiscal')

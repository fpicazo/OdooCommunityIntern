from odoo import models, fields, api, _

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    unidad_negocio = fields.Selection(
        [('bioseguridad', 'Bioseguridad'),
         ('mantenimiento', 'Mantenimiento'),
         ('taller', 'Taller'),
         ('mineral', 'Mineral')],
        string="Unidad de Negocio"
    )

    @api.model
    def create(self, vals):
        # Check if 'unidad_negocio' is in the values
        if 'unidad_negocio' in vals:
            unidad_negocio = vals['unidad_negocio']
            # Set the prefix based on the selected Unidad de Negocio
            if unidad_negocio == 'bioseguridad':
                vals['name'] = self.env['ir.sequence'].next_by_code('sale.order.bio') or _('New')
            elif unidad_negocio == 'mantenimiento':
                vals['name'] = self.env['ir.sequence'].next_by_code('sale.order.maint') or _('New')
            elif unidad_negocio == 'taller':
                vals['name'] = self.env['ir.sequence'].next_by_code('sale.order.taller') or _('New')
            elif unidad_negocio == 'mineral':
                vals['name'] = self.env['ir.sequence'].next_by_code('sale.order.mineral') or _('New')
        return super(SaleOrder, self).create(vals)

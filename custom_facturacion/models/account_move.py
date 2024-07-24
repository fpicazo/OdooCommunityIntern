# invoice_button_draft/models/account_move.py
from odoo import models, api, fields, _
from odoo.exceptions import UserError
import json
import base64

class AccountMove(models.Model):
    _inherit = 'account.move'

    modo_pago = fields.Selection([
        ('PUE', 'PUE'),
        ('PPD', 'PPD')
    ], string='Modo de Pago')

    uso_cfdi = fields.Selection([
        ('G01', 'Adquisición de mercancías'),
        ('G02', 'Devoluciones, descuentos o bonificaciones'),
        ('G03', 'Gastos en general'),
        ('I01', 'Construcciones'),
        ('I02', 'Mobiliario y equipo de oficina por inversiones'),
        ('I03', 'Equipo de transporte'),
        ('I04', 'Equipo de computo y accesorios'),
        ('I05', 'Dados, troqueles, moldes, matrices y herramental'),
        ('I06', 'Comunicaciones telefónicas'),
        ('I07', 'Comunicaciones satelitales'),
        ('I08', 'Otra maquinaria y equipo'),
        ('D01', 'Honorarios médicos, dentales y gastos hospitalarios'),
        ('D02', 'Gastos médicos por incapacidad o discapacidad'),
        ('D03', 'Gastos funerales'),
        ('D04', 'Donativos'),
        ('D05', 'Intereses reales efectivamente pagados por créditos hipotecarios (casa habitación)'),
        ('D06', 'Aportaciones voluntarias al SAR'),
        ('D07', 'Primas por seguros de gastos médicos'),
        ('D08', 'Gastos de transportación escolar obligatoria'),
        ('D09', 'Depósitos en cuentas para el ahorro, primas que tengan como base planes de pensiones'),
        ('D10', 'Pagos por servicios educativos (colegiaturas)'),
        ('S01', 'Sin efectos fiscales'),
        ('CP01', 'Pagos'),
        ('CN01', 'Nómina')
    ], string='Uso CFDI')

    state = fields.Selection(selection_add=[
        ('timbrado', 'Timbrado')
    ], ondelete={'timbrado': 'set default'})


    def action_custom_button(self):
        for record in self:
            if record.state != 'posted':
                raise UserError(_('You can only perform this action in the posted state.'))

            # Gather required data
            emisor = {
                "Rfc": record.company_id.vat or "",
                "Nombre": record.company_id.name or "",
                "RegimenFiscal": record.company_id.l10n_mx_edi_fiscal_regime or ""
            }
            
            receptor = {
                "Rfc": record.partner_id.vat or "",
                "Nombre": record.partner_id.name or "",
                "DomicilioFiscalReceptor": record.partner_id.zip or "",
                "RegimenFiscalReceptor": record.partner_id.l10n_mx_edi_fiscal_regime or "",
                "UsoCFDI": record.partner_id.l10n_mx_edi_usage or ""
            }
            
            conceptos = []
            total_traslados = 0.0
            total_retenciones = 0.0
            traslados = []
            retenciones = []
            
            for line in record.invoice_line_ids:
                impuestos = {
                    "Traslados": [],
                    "Retenciones": []
                }
                for tax in line.tax_ids:
                    if tax.amount > 0:
                        impuestos["Traslados"].append({
                            "Base": str(line.price_subtotal),
                            "Importe": str(line.price_subtotal * tax.amount / 100),
                            "Impuesto": "002",
                            "TasaOCuota": str(tax.amount / 100),
                            "TipoFactor": "Tasa"
                        })
                        total_traslados += line.price_subtotal * tax.amount / 100
                        traslados.append(impuestos["Traslados"][-1])
                    else:
                        impuestos["Retenciones"].append({
                            "Base": str(line.price_subtotal),
                            "Importe": str(-line.price_subtotal * tax.amount / 100),
                            "Impuesto":   "002",
                            "TasaOCuota": str(-tax.amount / 100),
                            "TipoFactor": "Tasa"
                        })
                        total_retenciones += -line.price_subtotal * tax.amount / 100
                        retenciones.append(impuestos["Retenciones"][-1])
                
                conceptos.append({
                    "ClaveProdServ": line.product_id.unspsc_code_id.code or "",
                    "NoIdentificacion": line.product_id.default_code or "None",
                    "Cantidad": str(line.quantity),
                    "ClaveUnidad": "E48",
                    "Unidad": line.product_uom_id.name or "Pieza",
                    "Descripcion": line.name or "",
                    "ValorUnitario": str(line.price_unit),
                    "Importe": str(line.price_subtotal),
                    "Descuento": "0.00",
                    "ObjetoImp": "02",
                    "Impuestos": impuestos
                })
            
            json_data = {
                "Version": "4.0",
                "FormaPago": record.l10n_mx_edi_payment_method_id.code or "01",
                "Serie": "SW",
                "Folio": record.name.split()[-1],
                "Fecha": record.invoice_date.strftime("%Y-%m-%dT%H:%M:%S"),
                "MetodoPago": record.l10n_mx_edi_payment_policy or "PUE",
                "Sello": "",
                "NoCertificado": "",
                "Certificado": "",
                "CondicionesDePago": record.invoice_payment_term_id.name or "CondicionesDePago",
                "SubTotal": str(record.amount_untaxed),
                "Descuento": "0.00",
                "Moneda": record.currency_id.name or "MXN",
                "Total": str(record.amount_total),
                "TipoDeComprobante": "I",
                "Exportacion": "01",
                "LugarExpedicion": record.company_id.zip or "",
                "Emisor": emisor,
                "Receptor": receptor,
                "Conceptos": conceptos,
                "Impuestos": {
                    "TotalImpuestosTrasladados": str(total_traslados),
                    "TotalImpuestosRetenidos": str(total_retenciones),
                    "Retenciones": retenciones,
                    "Traslados": traslados
                }
            }
            
            json_str = json.dumps(json_data, ensure_ascii=False)

            # Create a binary attachment
            attachment = self.env['ir.attachment'].create({
                'name': f'{record.name}_factura_fiscal.json',
                'type': 'binary',
                'datas': base64.b64encode(json_str.encode('utf-8')),
                'res_model': 'account.move',
                'res_id': record.id,
                'mimetype': 'application/json',
            })

            # Move the invoice to the next stage (e.g., 'posted')
            record.state = 'timbrado'

            # Refresh the view to reflect changes
            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }

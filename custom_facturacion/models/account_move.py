# models/account_move_res_company.py

from odoo import models, api, fields, _
from odoo.exceptions import UserError
import requests
import json
import base64

token = 'Bearer T2lYQ0t4L0RHVkR4dHZ5Nkk1VHNEakZ3Y0J4Nk9GODZuRyt4cE1wVm5tbXB3YVZxTHdOdHAwVXY2NTdJb1hkREtXTzE3dk9pMmdMdkFDR2xFWFVPUXpTUm9mTG1ySXdZbFNja3FRa0RlYURqbzdzdlI2UUx1WGJiKzViUWY2dnZGbFloUDJ6RjhFTGF4M1BySnJ4cHF0YjUvbmRyWWpjTkVLN3ppd3RxL0dJPQ.T2lYQ0t4L0RHVkR4dHZ5Nkk1VHNEakZ3Y0J4Nk9GODZuRyt4cE1wVm5tbFlVcU92YUJTZWlHU3pER1kySnlXRTF4alNUS0ZWcUlVS0NhelhqaXdnWTRncklVSWVvZlFZMWNyUjVxYUFxMWFxcStUL1IzdGpHRTJqdS9Zakw2UGRIanhVK1NteUdKZTJVVW51dGtnYW5QM2JKOG5tRWJQUlBtZFZaQ3NhaXF5R050ODNKTngxOVN2azVGZlMwcnF3MUNaQWNCcksvaUdSVjJwUU9MZjAxdkFGTGdTb2pxK2JEWm4xczlOMytSMStMZXhMeHZReCtNQUZwWG1YWlZFY0xKSFF2MGxUQTlZNEEwcjBGbk5CQ1lKSFpkamdMVTlDSmx2YXN6dUdPTTVtUUUxTjBaMnlCYURYTS9jSjdDbjhIbnhoQW1aRWpoQmV2ZERyRDA2MnY4Y2J0aXdSaDY0SzNiVExRNGtmMGV3OWVSZW9uQmJmaWlGZU5QOFpsYUJDNXNGSXIxMkxTZ2YzZUVVRWRHeWJoL1lnY3ZxblExQ1QwajhRNGZlQVNxNkd2L280cTRST1A4UkVQamFDK3J2SnB0b3RPK00zYkt3aHV3OTFwaWFFeWNHU2ZXZ1owQnlJK2VadkNzOUJPTVliNzRheFFsNkN1SURCMUVxdEVrd2E2dVdMVFEvSmNKWGxQb0dRUFdGUEt3PT0.VtMmvV72pmXTPJPaf4qYIjhNjEzLRlX-XiV2Y3DxVFU'

# AccountMove class
class AccountMove(models.Model):
    _inherit = 'account.move'

    modo_pago = fields.Selection([
        ('PUE', 'PUE'),
        ('PPD', 'PPD')
    ], string='Modo de Pago')

    payment_method = fields.Selection([
    ('01', 'Efectivo'),
    ('02', 'Cheque nominativo'),
    ('03', 'Transferencia electrónica de fondos'),
    ('04', 'Tarjeta de crédito'),
    ('05', 'Monedero electrónico'),
    ('06', 'Dinero electrónico'),
    ('08', 'Vales de despensa'),
    ('12', 'Dación en pago'),
    ('13', 'Pago por subrogación'),
    ('14', 'Pago por consignación'),
    ('15', 'Condonación'),
    ('17', 'Compensación'),
    ('23', 'Novación'),
    ('24', 'Confusión'),
    ('25', 'Remisión de deuda'),
    ('26', 'Prescripción o caducidad'),
    ('27', 'A satisfacción del acreedor'),
    ('28', 'Tarjeta de débito'),
    ('29', 'Tarjeta de servicios'),
    ('30', 'Aplicación de anticipos'),
    ('99', 'Por definir')
], string='Método de Pago')

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

    folio_fiscal = fields.Char(string="Folio Fiscal")

    state = fields.Selection(selection_add=[
        ('timbrado', 'Timbrado')
    ], ondelete={'timbrado': 'set default'})

    def action_custom_button(self):
        for record in self:
            if record.state != 'posted':
                raise UserError(_('You can only perform this action in the posted state.'))


            # Validation
            if not record.partner_id.vat:
                raise UserError(_('El campo RFC del receptor es obligatorio.'))
            if not record.partner_id.name:
                raise UserError(_('El campo Nombre del receptor es obligatorio.'))
            if not record.partner_id.zip:
                raise UserError(_('El campo Domicilio Fiscal del receptor es obligatorio.'))
            if not record.partner_id.regimen_fiscal:
                raise UserError(_('El campo Régimen Fiscal del receptor es obligatorio.'))
            if not record.modo_pago:
                raise UserError(_('El campo Modo de Pago es obligatorio.'))
            if not record.payment_method:
                raise UserError(_('El campo Método de Pago es obligatorio.'))
            
            # Validation for invoice lines
            for line in record.invoice_line_ids:
                if not line.product_id.sat_unit_code:
                    raise UserError(_('El campo Código SAT de Unidad es obligatorio en las líneas de producto.'))
                if not line.product_id.sat_code_product:
                    raise UserError(_('El campo Código SAT del Producto es obligatorio en las líneas de producto.'))
            # Gather required data
            emisor = {
                "Rfc": record.company_id.vat or "",
                 "Nombre": (record.company_id.name or "").upper(),  # Convert to uppercase
                "RegimenFiscal": record.company_id.l10n_mx_edi_fiscal_regime or ""
            }

            receptor = {
                "Rfc": record.partner_id.vat or "",
                "Nombre": (record.partner_id.name or "").upper(),  # Convert to uppercase
                "DomicilioFiscalReceptor": record.partner_id.zip or "",
                "RegimenFiscalReceptor": record.partner_id.regimen_fiscal or "",
                "UsoCFDI": record.uso_cfdi or ""
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
                impuestos_data_concepto = {}

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
                            "Impuesto": "002",
                            "TasaOCuota": str(-tax.amount / 100),
                            "TipoFactor": "Tasa"
                        })
                        total_retenciones += -line.price_subtotal * tax.amount / 100
                        retenciones.append(impuestos["Retenciones"][-1])


                if len(retenciones) > 0:
                    impuestos_data_concepto["Retenciones"] = retenciones

                if len(traslados) > 0:
                    impuestos_data_concepto["Traslados"] = traslados

                conceptos.append({
                    "ClaveProdServ": line.product_id.sat_unit_code or "",
                    "NoIdentificacion": line.product_id.sat_code_product or "None",
                    "Cantidad": str(line.quantity),
                    "ClaveUnidad": "E48",
                    "Unidad": line.product_uom_id.name or "Pieza",
                    "Descripcion": line.name or "",
                    "ValorUnitario": str(line.price_unit),
                    "Importe": str(line.price_subtotal),
                    "Descuento": "0.00",
                    "ObjetoImp": "02",
                    "Impuestos": impuestos_data_concepto
                })

            # Construct the Impuestos dictionary, adding Retenciones only if it's not empty
            impuestos_data = {
                "TotalImpuestosTrasladados": str(total_traslados),
                "Traslados": traslados
            }

            # Only include Retenciones if there are retentions
            if len(retenciones) > 0:
                impuestos_data["Retenciones"] = retenciones
                impuestos_data["TotalImpuestosRetenidos"] = str(total_retenciones)

            # Construct the JSON payload
            json_data = {
                "Version": "4.0",
                "FormaPago": record.payment_method or "99",
                "Serie": "SW",
                "Folio": record.name.split()[-1],
                "Fecha": record.invoice_date.strftime("%Y-%m-%dT%H:%M:%S"),
                "MetodoPago": record.modo_pago or "PUE",
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
                "Impuestos": impuestos_data
            }

            json_str = json.dumps(json_data, ensure_ascii=False)

            # Save the generated JSON as an attachment in the Odoo record
            attachment = self.env['ir.attachment'].create({
                'name': f'{record.name}_factura_fiscal.json',
                'type': 'binary',
                'datas': base64.b64encode(json_str.encode('utf-8')),
                'res_model': 'account.move',
                'res_id': record.id,
                'mimetype': 'application/json',
            })
            # API Call to External Service
            url = "https://services.sw.com.mx/v4/cfdi33/issue/json/v1"
            headers = {
                'Authorization': token,
                'Content-Type': 'application/jsontoxml'
            }
            """
            try:
                response = requests.post(url, headers=headers, data=json_str)
                response.raise_for_status()

                # Store API response as attachment
                response_text = response.text
                attachment = self.env['ir.attachment'].create({
                    'name': f'{record.name}_api_response.txt',
                    'type': 'binary',
                    'datas': base64.b64encode(response_text.encode('utf-8')),
                    'res_model': 'account.move',
                    'res_id': record.id,
                    'mimetype': 'text/plain',
                })

            except requests.exceptions.HTTPError as e:
                # If an error occurs, try to extract 'messageDetail' from the response
                try:
                    error_message = response.json().get('messageDetail', str(e))
                except Exception:
                    error_message = str(e)

                raise UserError(_("Error in API call: %s") % error_message)
            # Move the invoice to the next stage (e.g., 'posted')
            #record.state = 'timbrado'
            """
            # Refresh the view to reflect changes
            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }



# ResCompany class
class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_mx_edi_fiscal_regime = fields.Selection([
        ('601', 'General de Ley de Personas Morales'),
        ('603', 'Personas morales con fines no lucrativos'),
        ('605', 'Sueldos y Salarios e Ingresos Asimilados a Salarios'),
        ('606', 'Arrendamiento'),
        ('607', 'Régimen de enajenación o adquisición de bienes'),
        ('608', 'Demás ingresos'),
        ('609', 'Consolidación'),
        ('610', 'Residentes en el extranjero sin establecimiento permanente en México'),
        ('611', 'Ingresos por Dividendos (socios y accionistas)'),
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
        ('630', 'Enajenación de acciones en bolsa de valores'),
    ], string='Régimen Fiscal', help="Fiscal Regime for CFDI 4.0")

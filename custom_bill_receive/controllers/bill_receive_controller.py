from odoo import http, fields
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)

class BillReceiveController(http.Controller):

    @http.route('/api/receive_bills', type='json', auth='public', methods=['POST'], csrf=False)
    def receive_bills(self, bills=None, **kwargs):
        try:
            if not bills:
                try:
                    raw = json.loads(request.httprequest.data.decode('utf-8'))
                    bills = raw.get('params', raw).get('bills', raw.get('bills', []))
                except Exception:
                    bills = []

            if not bills:
                return {'error': 'No bills data received'}

            _logger.info(f"Received {len(bills)} bills to process")

            created_bills = []
            errors = []
            for bill_data in bills:
                try:
                    partner = request.env['res.partner'].sudo().search([
                        ('name', '=', bill_data['partner_id']['name']),
                        ('vat', '=', bill_data['partner_id']['vat'])
                    ], limit=1)
                    if not partner:
                        partner = request.env['res.partner'].sudo().create({
                            'name': bill_data['partner_id']['name'],
                            'vat': bill_data['partner_id']['vat'],
                            'supplier_rank': 1,
                        })

                    currency = None
                    if 'currency_code' in bill_data:
                        currency = request.env['res.currency'].sudo().search([
                            ('name', '=', bill_data['currency_code'])
                        ], limit=1)
                        if not currency:
                            errors.append({'bill_data': bill_data, 'error': f"Currency '{bill_data['currency_code']}' not found."})
                            continue
                    else:
                        currency = request.env['res.currency'].sudo().search([('name', '=', 'USD')], limit=1)
                        if not currency:
                            errors.append({'bill_data': bill_data, 'error': "USD currency not found."})
                            continue

                    invoice_line_ids = []
                    for line in bill_data['invoice_line_ids']:
                        product = request.env['product.product'].sudo().search([
                            ('name', '=', line['name'])
                        ], limit=1)
                        if not product:
                            product = request.env['product.product'].sudo().create({
                                'name': line['name'],
                                'type': 'service',
                            })

                        tax_ids = []
                        for tax in line.get('tax_ids', []):
                            existing_tax = request.env['account.tax'].sudo().search([
                                ('name', '=', tax['name'])
                            ], limit=1)
                            if existing_tax:
                                tax_ids.append(existing_tax.id)
                            else:
                                try:
                                    new_tax = request.env['account.tax'].sudo().create({
                                        'name': tax['name'],
                                        'amount': tax['amount'],
                                        'type_tax_use': 'purchase',
                                    })
                                    tax_ids.append(new_tax.id)
                                except Exception as e:
                                    errors.append({
                                        'line_item': line,
                                        'error': f'Failed to create tax: {str(e)}'
                                    })
                                    continue

                        invoice_line_ids.append((0, 0, {
                            'name': line['name'],
                            'quantity': line['quantity'],
                            'price_unit': line['price_unit'],
                            'account_id': line['account_id'],
                            'product_id': product.id,
                            'tax_ids': [(6, 0, tax_ids)]
                        }))

                    bill_vals = {
                        'move_type': bill_data['move_type'],
                        'journal_id': bill_data['journal_id'],
                        'ref': bill_data.get('name', ''),
                        'invoice_date': bill_data['invoice_date'],
                        'invoice_date_due': bill_data.get('invoice_date_due', bill_data['invoice_date']),
                        'partner_id': partner.id,
                        'invoice_line_ids': invoice_line_ids,
                        'l10n_mx_edi_cfdi_uuid': bill_data.get('l10n_mx_edi_cfdi_uuid', ''),
                        'currency_id': currency.id
                    }

                    bill = request.env['account.move'].sudo().create(bill_vals)
                    bill.action_post()

                    if 'payment_data' in bill_data:
                        payment_data = bill_data['payment_data']
                        payment_register = request.env['account.payment.register'].sudo().with_context(
                            active_model='account.move',
                            active_ids=[bill.id],
                        ).create({
                            'payment_date': payment_data['payment_date'],
                            'journal_id': payment_data['journal_id'],
                            'amount': payment_data['amount'],
                        })
                        payment = payment_register._create_payments()
                        _logger.info(f"Registered payment {payment.id} for bill {bill.id}")

                    created_bills.append(bill.id)
                    cfdi_uuid = bill_data.get('l10n_mx_edi_cfdi_uuid', '')
                    if cfdi_uuid:
                        bill.sudo().write({'l10n_mx_edi_cfdi_uuid': cfdi_uuid})
                    _logger.info(f"Created bill {bill.id} for {bill_data['partner_id']['name']}")
                except Exception as e:
                    request.env.cr.rollback()
                    _logger.error(f"Error processing bill: {str(e)}", exc_info=True)
                    errors.append({'bill_data': bill_data, 'error': str(e)})
                    continue

            return {
                'success': 'Bills processed',
                'created_bills': created_bills,
                'errors': errors
            }
        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Failed to process bills request: {str(e)}", exc_info=True)
            return {
                'error': 'Failed to process the request',
                'details': str(e)
            }


    @http.route('/api/receive_invoices', type='json', auth='public', methods=['POST'], csrf=False)
    def receive_invoices(self, invoices=None, **kwargs):
        try:
            if not invoices:
                try:
                    raw = json.loads(request.httprequest.data.decode('utf-8'))
                    invoices = raw.get('params', raw).get('invoices', raw.get('invoices', []))
                except Exception:
                    invoices = []

            if not invoices:
                return {'error': 'No invoices data received'}

            _logger.info(f"Received {len(invoices)} invoices to process")

            created_invoices = []
            errors = []
            for invoice_data in invoices:
                try:
                    partner = request.env['res.partner'].sudo().search([
                        ('name', '=', invoice_data['partner_id']['name']),
                        ('vat', '=', invoice_data['partner_id']['vat'])
                    ], limit=1)
                    if not partner:
                        partner = request.env['res.partner'].sudo().create({
                            'name': invoice_data['partner_id']['name'],
                            'vat': invoice_data['partner_id']['vat'],
                            'customer_rank': 1,
                        })

                    currency = request.env['res.currency'].sudo().search([
                        ('name', '=', invoice_data['currency_code'])
                    ], limit=1)
                    if not currency:
                        raise ValueError(f"Currency '{invoice_data['currency_code']}' not found.")

                    invoice_line_ids = []
                    for line in invoice_data['invoice_line_ids']:
                        product = request.env['product.product'].sudo().search([
                            ('name', '=', line['name'])
                        ], limit=1)
                        if not product:
                            product = request.env['product.product'].sudo().create({
                                'name': line['name'],
                                'type': 'service',
                            })

                        tax_ids = []
                        for tax in line.get('tax_ids', []):
                            existing_tax = request.env['account.tax'].sudo().search([
                                ('name', '=', tax['name'])
                            ], limit=1)
                            if existing_tax:
                                tax_ids.append(existing_tax.id)
                            else:
                                new_tax = request.env['account.tax'].sudo().create({
                                    'name': tax['name'],
                                    'amount': tax['amount'],
                                    'type_tax_use': 'sale',
                                })
                                tax_ids.append(new_tax.id)

                        resolved_account_id = False
                        requested_account_id = line.get('account_id')
                        if requested_account_id:
                            requested_account = request.env['account.account'].sudo().browse(requested_account_id).exists()
                            if requested_account and requested_account.account_type not in ('asset_receivable', 'liability_payable'):
                                resolved_account_id = requested_account.id
                            else:
                                _logger.warning(
                                    "Invalid account_id %s for invoice line '%s'. "
                                    "Expected an income/other account, not receivable/payable.",
                                    requested_account_id, line['name']
                                )

                        if not resolved_account_id:
                            income_account = product.property_account_income_id or product.categ_id.property_account_income_categ_id
                            if income_account and income_account.account_type not in ('asset_receivable', 'liability_payable'):
                                resolved_account_id = income_account.id

                        if not resolved_account_id:
                            raise ValueError(
                                f"No valid income account found for invoice line '{line['name']}'. "
                                "Provide a valid income account_id."
                            )

                        invoice_line_ids.append((0, 0, {
                            'name': line['name'],
                            'quantity': line['quantity'],
                            'price_unit': line['price_unit'],
                            'account_id': resolved_account_id,
                            'product_id': product.id,
                            'tax_ids': [(6, 0, tax_ids)]
                        }))

                    modo_pago_code = invoice_data.get('modo_pago', '99')
                    payment_method = request.env['l10n_mx_edi.payment.method'].sudo().search([
                        ('code', '=', modo_pago_code)
                    ], limit=1)

                    invoice_vals = {
                        'move_type': invoice_data['move_type'],
                        'journal_id': invoice_data['journal_id'],
                        'ref': invoice_data.get('name', ''),
                        'l10n_mx_edi_cfdi_uuid': invoice_data.get('l10n_mx_edi_cfdi_uuid', ''),
                        'invoice_date': invoice_data['invoice_date'],
                        'invoice_date_due': invoice_data.get('invoice_date_due', invoice_data['invoice_date']),
                        'partner_id': partner.id,
                        "l10n_mx_edi_cfdi_to_public": False,
                        'invoice_line_ids': invoice_line_ids,
                        'l10n_mx_edi_usage': invoice_data.get('uso_cfdi', 'G03'),
                        'l10n_mx_edi_payment_method_id': payment_method.id if payment_method else False,
                        'currency_id': currency.id
                    }
                    
                    if invoice_data.get('invoice_name'):
                        invoice_vals['name'] = invoice_data['invoice_name']

                    invoice = request.env['account.move'].sudo().create(invoice_vals)
                    invoice.action_post()
                    created_invoices.append(invoice.id)

                    cfdi_uuid = invoice_data.get('l10n_mx_edi_cfdi_uuid', '')
                    if cfdi_uuid:
                        invoice.sudo().write({'l10n_mx_edi_cfdi_uuid': cfdi_uuid})

                    _logger.info(f"Created invoice {invoice.id} for {invoice_data['partner_id']['name']}")
                except Exception as e:
                    request.env.cr.rollback()
                    _logger.error(f"Error processing invoice: {str(e)}", exc_info=True)
                    errors.append({'invoice_data': invoice_data, 'error': str(e)})
                    continue

            return {
                'success': 'Invoices processed',
                'created_invoices': created_invoices,
                'errors': errors
            }
        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Failed to process invoices request: {str(e)}", exc_info=True)
            return {
                'error': 'Failed to process the request',
                'details': str(e)
            }

    @http.route('/api/register_invoice_payment', type='json', auth='public', methods=['POST'], csrf=False)
    def register_invoice_payment(self, uuid=None, payment_data=None, **kwargs):
        try:
            payload = {}
            if not uuid or not payment_data:
                try:
                    raw = json.loads(request.httprequest.data.decode('utf-8'))
                    payload = raw.get('params', raw)
                except Exception:
                    payload = {}

            uuid = uuid or payload.get('uuid') or payload.get('invoice_uuid')
            payment_data = payment_data or payload.get('payment_data', {})

            if not uuid:
                return {'error': 'Missing uuid (or invoice_uuid)'}
            if not payment_data:
                return {'error': 'Missing payment_data'}
            if not payment_data.get('journal_id'):
                return {'error': 'Missing payment_data.journal_id'}

            account_move = request.env['account.move'].sudo()
            search_domain = [
                ('move_type', 'in', ['out_invoice', 'out_refund']),
                ('state', '=', 'posted'),
            ]

            uuid_filters = []
            if 'folio_fiscal' in account_move._fields:
                uuid_filters.append(('folio_fiscal', '=', uuid))
            if 'l10n_mx_edi_cfdi_uuid' in account_move._fields:
                uuid_filters.append(('l10n_mx_edi_cfdi_uuid', '=', uuid))

            if not uuid_filters:
                return {'error': 'No UUID field available on account.move (expected folio_fiscal or l10n_mx_edi_cfdi_uuid).'}

            if len(uuid_filters) == 1:
                search_domain.append(uuid_filters[0])
            else:
                search_domain += ['|', uuid_filters[0], uuid_filters[1]]

            invoice = account_move.search(search_domain, limit=1)
            if not invoice:
                return {'error': f"Invoice not found for UUID '{uuid}'"}

            pay_journal = request.env['account.journal'].sudo().browse(payment_data['journal_id']).exists()
            if not pay_journal:
                return {'error': f"Journal not found (id={payment_data['journal_id']})"}

            pay_method_line = pay_journal.inbound_payment_method_line_ids[:1]
            if not pay_method_line:
                return {'error': f"No inbound payment method configured on journal '{pay_journal.name}' (id={pay_journal.id})."}

            currency = invoice.currency_id
            currency_code = payment_data.get('currency_code')
            if currency_code:
                found_currency = request.env['res.currency'].sudo().search([('name', '=', currency_code)], limit=1)
                if not found_currency:
                    return {'error': f"Currency '{currency_code}' not found."}
                currency = found_currency

            inv_receivable_line = invoice.line_ids.filtered(
                lambda l: l.account_id.account_type == 'asset_receivable'
            )[:1]
            if not inv_receivable_line:
                return {'error': f"Invoice {invoice.id} has no receivable line to pay."}

            receivable_account = inv_receivable_line.account_id

            amount = payment_data.get('amount', invoice.amount_residual)
            payment_date = payment_data.get('payment_date', fields.Date.context_today(request.env.user))

            payment = request.env['account.payment'].sudo().create({
                'payment_type': 'inbound',
                'partner_type': 'customer',
                'partner_id': invoice.partner_id.id,
                'amount': amount,
                'date': payment_date,
                'journal_id': pay_journal.id,
                'currency_id': currency.id,
                'payment_method_line_id': pay_method_line.id,
                'destination_account_id': receivable_account.id,
            })
            payment.action_post()

            invoice_lines = invoice.line_ids.filtered(
                lambda l: not l.reconciled and l.account_id.account_type == 'asset_receivable'
            )
            if not invoice_lines:
                invoice_lines = invoice.line_ids.filtered(
                    lambda l: not l.reconciled and l.account_id.internal_group == 'receivable'
                )

            payment_lines = payment.move_id.line_ids.filtered(
                lambda l: not l.reconciled and l.account_id.account_type == 'asset_receivable'
            )
            if not payment_lines:
                payment_lines = payment.move_id.line_ids.filtered(
                    lambda l: not l.reconciled and l.account_id.internal_group == 'receivable'
                )

            lines_to_reconcile = invoice_lines + payment_lines
            if lines_to_reconcile:
                lines_to_reconcile.reconcile()
            else:
                _logger.warning(
                    "No unreconciled receivable lines found for invoice %s / payment %s",
                    invoice.id, payment.id
                )

            _logger.info("Registered payment %s and reconciled invoice %s using UUID %s", payment.id, invoice.id, uuid)
            return {
                'success': 'Payment registered and applied',
                'invoice_id': invoice.id,
                'payment_id': payment.id,
                'uuid': uuid,
            }
        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Failed to register invoice payment: {str(e)}", exc_info=True)
            return {
                'error': 'Failed to register payment',
                'details': str(e)
            }

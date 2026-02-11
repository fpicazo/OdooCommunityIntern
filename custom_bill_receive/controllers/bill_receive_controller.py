from odoo import http
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)

class BillReceiveController(http.Controller):

    @http.route('/api/receive_bills', type='json', auth='public', methods=['POST'], csrf=False)
    def receive_bills(self, bills=None, **kwargs):
        try:
            # type='json' + JSON-RPC: Odoo extracts params automatically as kwargs
            # So bills comes directly from params.bills
            if not bills:
                # Fallback: try parsing raw body (for non-JSON-RPC direct calls)
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
                    # Find or create vendor
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

                    # Find or set currency
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

                    bill = request.env['account.move'].sudo().create({
                        'move_type': bill_data['move_type'],
                        'journal_id': bill_data['journal_id'],
                        'state': 'draft',
                        'name': bill_data['name'],
                        'amount_total': bill_data['amount_total'],
                        'folio_fiscal': bill_data['folio_fiscal'],
                        'invoice_date': bill_data['invoice_date'],
                        'invoice_date_due': bill_data['invoice_date'],
                        'partner_id': partner.id,
                        'invoice_line_ids': invoice_line_ids,
                        'currency_id': currency.id
                    })

                    bill.action_post()

                    if 'payment_data' in bill_data:
                        payment_data = bill_data['payment_data']
                        payment = request.env['account.payment'].sudo().create({
                            'payment_type': 'outbound',
                            'partner_type': 'supplier',
                            'partner_id': partner.id,
                            'amount': payment_data['amount'],
                            'date': payment_data['payment_date'],
                            'journal_id': payment_data['journal_id'],
                            'currency_id': currency.id,
                            'payment_method_id': request.env.ref('account.account_payment_method_manual_out').id,
                        })
                        payment.action_post()

                        payment_lines = payment.move_id.line_ids.filtered(
                            lambda line: line.account_id.internal_group == 'payable'
                        )
                        bill_lines = bill.line_ids.filtered(
                            lambda line: line.account_id.internal_group == 'payable'
                        )
                        (payment_lines + bill_lines).reconcile()

                    created_bills.append(bill.id)
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

                        invoice_line_ids.append((0, 0, {
                            'name': line['name'],
                            'quantity': line['quantity'],
                            'price_unit': line['price_unit'],
                            'account_id': line['account_id'],
                            'product_id': product.id,
                            'tax_ids': [(6, 0, tax_ids)]
                        }))

                    invoice = request.env['account.move'].sudo().create({
                        'move_type': invoice_data['move_type'],
                        'journal_id': invoice_data['journal_id'],
                        'state': 'draft',
                        'name': invoice_data['name'],
                        'amount_total': invoice_data['amount_total'],
                        'folio_fiscal': invoice_data['folio_fiscal'],
                        'invoice_date': invoice_data['invoice_date'],
                        'invoice_date_due': invoice_data['invoice_date_due'],
                        'partner_id': partner.id,
                        'invoice_line_ids': invoice_line_ids,
                        'uso_cfdi': invoice_data.get('uso_cfdi', 'G03'),
                        'modo_pago': invoice_data.get('modo_pago', '99'),
                        'currency_id': currency.id
                    })
                    invoice.action_post()
                    created_invoices.append(invoice.id)

                    if 'payment_data' in invoice_data:
                        payment_data = invoice_data['payment_data']
                        payment = request.env['account.payment'].sudo().create({
                            'payment_type': 'inbound',
                            'partner_type': 'customer',
                            'partner_id': partner.id,
                            'amount': payment_data['amount'],
                            'date': payment_data['payment_date'],
                            'journal_id': payment_data['journal_id'],
                            'currency_id': currency.id,
                            'payment_method_id': request.env.ref('account.account_payment_method_manual_in').id,
                        })
                        payment.action_post()

                        payment_lines = payment.move_id.line_ids.filtered(
                            lambda line: line.account_id.internal_group == 'receivable'
                        )
                        invoice_lines = invoice.line_ids.filtered(
                            lambda line: line.account_id.internal_group == 'receivable'
                        )
                        (payment_lines + invoice_lines).reconcile()

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

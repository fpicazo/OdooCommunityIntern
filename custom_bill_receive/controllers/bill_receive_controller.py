from odoo import http
from odoo.http import request
import json

class BillReceiveController(http.Controller):

    @http.route('/api/receive_bills', type='json', auth='public', methods=['POST'], csrf=False)
    def receive_bills(self, **kwargs):
        try:
            data = json.loads(request.httprequest.data.decode('utf-8'))
            bills_data = data.get('bills', [])

            if not bills_data:
                return {'error': 'No bills data received'}

            created_bills = []
            errors = []
            for bill_data in bills_data:
                try:
                    # Find or create vendor
                    partner = request.env['res.partner'].sudo().search([('name', '=', bill_data['partner_id']['name']), ('vat', '=', bill_data['partner_id']['vat'])], limit=1)
                    if not partner:
                        partner = request.env['res.partner'].sudo().create({
                            'name': bill_data['partner_id']['name'],
                            'vat': bill_data['partner_id']['vat'],
                            'supplier_rank': 1,  # Ensure it's marked as a vendor
                        })

                    invoice_line_ids = []
                    for line in bill_data['invoice_line_ids']:
                        # Find or create product
                        product = request.env['product.product'].sudo().search([('name', '=', line['name'])], limit=1)
                        if not product:
                            product = request.env['product.product'].sudo().create({
                                'name': line['name'],
                                'type': 'service',  # Adjust product type if necessary
                            })
                        invoice_line_ids.append((0, 0, {
                            'name': line['name'],
                            'quantity': line['quantity'],
                            'price_unit': line['price_unit'],
                            'account_id': line['account_id'],
                            'product_id': product.id,
                        }))

                    bill = request.env['account.move'].sudo().create({
                        'move_type': bill_data['move_type'],  # Specify the type of move
                        'journal_id': bill_data['journal_id'],  # Ensure this is a valid journal ID
                        'state': 'draft',  # Set the state to draft or posted as needed
                        'name': bill_data['name'],
                        'amount_total': bill_data['amount_total'],
                        'folio_fiscal': bill_data['folio_fiscal'],
                        'invoice_date': bill_data['invoice_date'],  # Date already in string format
                        'invoice_date_due': bill_data['invoice_date'],
                        'partner_id': partner.id,  # Set the vendor
                        'invoice_line_ids': invoice_line_ids,
                        # Add more fields as needed
                    })
                    created_bills.append(bill.id)
                except Exception as e:
                    errors.append({'bill_data': bill_data, 'error': str(e)})

            return {
                'success': 'Bills processed',
                'created_bills': created_bills,
                'errors': errors
            }
        except Exception as e:
            return {
                'error': 'Failed to process the request',
                'details': str(e)
            }

    @http.route('/api/receive_invoices', type='json', auth='public', methods=['POST'], csrf=False)
    def receive_invoices(self, **kwargs):
        try:
            data = json.loads(request.httprequest.data.decode('utf-8'))
            invoices_data = data.get('invoices', [])

            if not invoices_data:
                return {'error': 'No invoices data received'}

            created_invoices = []
            errors = []
            for invoice_data in invoices_data:
                try:
                    # Find or create customer
                    partner = request.env['res.partner'].sudo().search([('name', '=', invoice_data['partner_id']['name']), ('vat', '=', invoice_data['partner_id']['vat'])], limit=1)
                    if not partner:
                        partner = request.env['res.partner'].sudo().create({
                            'name': invoice_data['partner_id']['name'],
                            'vat': invoice_data['partner_id']['vat'],
                            'customer_rank': 1,  # Ensure it's marked as a customer
                        })

                    invoice_line_ids = []
                    for line in invoice_data['invoice_line_ids']:
                        # Find or create product
                        product = request.env['product.product'].sudo().search([('name', '=', line['name'])], limit=1)
                        if not product:
                            product = request.env['product.product'].sudo().create({
                                'name': line['name'],
                                'type': 'service',  # Adjust product type if necessary
                            })
                        invoice_line_ids.append((0, 0, {
                            'name': line['name'],
                            'quantity': line['quantity'],
                            'price_unit': line['price_unit'],
                            'account_id': line['account_id'],
                            'product_id': product.id,
                        }))

                    invoice = request.env['account.move'].sudo().create({
                        'move_type': invoice_data['move_type'],  # Specify the type of move
                        'journal_id': invoice_data['journal_id'],  # Ensure this is a valid journal ID
                        'state': 'draft',  # Set the state to draft or posted as needed
                        'name': invoice_data['name'],
                        'amount_total': invoice_data['amount_total'],
                        'folio_fiscal': invoice_data['folio_fiscal'],
                        'invoice_date': invoice_data['invoice_date'],  # Date already in string format
                        'partner_id': partner.id,  # Set the customer
                        'invoice_line_ids': invoice_line_ids,
                        # Add more fields as needed
                    })
                    created_invoices.append(invoice.id)
                except Exception as e:
                    errors.append({'invoice_data': invoice_data, 'error': str(e)})

            return {
                'success': 'Invoices processed',
                'created_invoices': created_invoices,
                'errors': errors
            }
        except Exception as e:
            return {
                'error': 'Failed to process the request',
                'details': str(e)
            }

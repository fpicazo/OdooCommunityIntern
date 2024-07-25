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

                    partner = request.env['res.partner'].sudo().search([('name', '=', bill_data['partner_id']['name']), ('vat', '=', bill_data['partner_id']['vat'])], limit=1)
                    if not partner:
                        partner = request.env['res.partner'].sudo().create({
                            'name': bill_data['partner_id']['name'],
                            'vat': bill_data['partner_id']['vat'],
                            'supplier_rank': 1,  # Ensure it's marked as a vendor
                        })


                    bill = request.env['account.move'].sudo().create({
                        'move_type': 'in_invoice',  # Specify the type of move, e.g., 'in_invoice' for supplier bills
                        'journal_id': 1,  # Specify the journal ID, ensure this is a valid journal ID
                        'state': 'draft',  # Set the state to draft or posted as needed
                        'name': bill_data['name'],
                        'amount_total': bill_data['amount_total'],
                        'folio_fiscal': bill_data['folio_fiscal'],
                        'invoice_date': bill_data['invoice_date'],
                        'partner_id': partner.id,  # Set the vendor
                        'invoice_line_ids': [(0, 0, {  # Add at least one line item
                            'name': 'Sample Product',  # Replace with actual product/service name
                            'quantity': 1,
                            'price_unit': bill_data['amount_total'],
                            'account_id': 41,  # Replace with an actual account ID
                        })],
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

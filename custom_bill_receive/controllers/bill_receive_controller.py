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
                    bill = request.env['account.move'].sudo().create({
                        'name': bill_data['name'],
                        'amount_total': bill_data['amount_total'],
                        'folio_fiscal': bill_data['folio_fiscal'],
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

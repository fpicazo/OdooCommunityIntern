from odoo import http
from odoo.http import request
import json 

class BillReceiveController(http.Controller):

    @http.route('/api/receive_bills', type='json', auth='public', methods=['POST'], csrf=False)
    def receive_bills(self, **kwargs):
        data = json.loads(request.httprequest.data.decode('utf-8'))
        bills_data = data.get('bills', [])
        
        if not bills_data:
            return {'error': 'No bills data received'}

        for bill_data in bills_data:
            request.env['account.move'].sudo().create({
                'name': bill_data['name'],
                'amount_total': bill_data['amount_total'],
                'folio_fiscal': bill_data['folio_fiscal'],
                # Add more fields as needed
            })

        return {'success': 'Bills received and created successfully'}

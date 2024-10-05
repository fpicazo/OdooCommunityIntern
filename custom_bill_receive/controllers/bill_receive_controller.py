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

                    # Find or set currency
                    currency = None
                    if 'currency_code' in bill_data:
                        currency = request.env['res.currency'].sudo().search([('name', '=', bill_data['currency_code'])], limit=1)
                        if not currency:
                            errors.append({'bill_data': bill_data, 'error': f"Currency '{bill_data['currency_code']}' not found."})
                            continue  # Skip this bill if currency is not found
                    else:
                        # Default to USD if no currency is provided
                        currency = request.env['res.currency'].sudo().search([('name', '=', 'USD')], limit=1)
                        if not currency:
                            errors.append({'bill_data': bill_data, 'error': "USD currency not found."})
                            continue  # Skip this bill if USD is not found

                    invoice_line_ids = []
                    for line in bill_data['invoice_line_ids']:
                        # Find or create product
                        product = request.env['product.product'].sudo().search([('name', '=', line['name'])], limit=1)
                        if not product:
                            product = request.env['product.product'].sudo().create({
                                'name': line['name'],
                                'type': 'service',  # Adjust product type if necessary
                            })

                        # Find applicable taxes
                        tax_ids = []
                        for tax in line.get('tax_ids', []):
                            existing_tax = request.env['account.tax'].sudo().search([('name', '=', tax['name'])], limit=1)
                            if existing_tax:
                                tax_ids.append(existing_tax.id)
                            else:
                                try:
                                    new_tax = request.env['account.tax'].sudo().create({
                                        'name': tax['name'],
                                        'amount': tax['amount'],
                                        'type_tax_use': 'purchase',  # Adjust for purchases
                                    })
                                    tax_ids.append(new_tax.id)
                                except Exception as e:
                                    errors.append({
                                        'line_item': line,
                                        'error': f'Failed to create tax: {str(e)}'
                                    })
                                    continue  # Skip tax creation if there's an issue

                        invoice_line_ids.append((0, 0, {
                            'name': line['name'],
                            'quantity': line['quantity'],
                            'price_unit': line['price_unit'],
                            'account_id': line['account_id'],
                            'product_id': product.id,
                            'tax_ids': [(6, 0, tax_ids)]  # Assign tax ids
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
                        'currency_id': currency.id  # Set currency (either provided or default to USD)
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
        
        """example request
        {
  "bills": [
    {
      "partner_id": {
        "name": "Vendor Name",
        "vat": "VENDOR_VAT_NUMBER"
      },
      "move_type": "in_invoice",  // For vendor bills
      "journal_id": 1,  // Valid journal ID for bills
      "name": "BILL_12345",
      "amount_total": 1000.0,
      "folio_fiscal": "FISCAL_FOLIO_12345",
      "invoice_date": "2024-10-02",
      "invoice_line_ids": [
        {
          "name": "Service/Product Name",
          "quantity": 10,
          "price_unit": 100.0,
          "account_id": 2,
          "tax_ids": [
            {
              "name": "VAT 10%",
              "amount": 10.0
            }
          ]
        }
      ]
    }
  ]
}
        """
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

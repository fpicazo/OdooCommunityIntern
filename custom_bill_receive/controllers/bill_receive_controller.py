from odoo import http, fields
from odoo.http import request
import json
import logging
import unicodedata

_logger = logging.getLogger(__name__)

class BillReceiveController(http.Controller):
    SPECIAL_DELETE_CATEGORY = 'santander no aplica - cambio'
    CATEGORY_TO_ACCOUNT_CODE = {
        'viaticos': '601.90.01',
        'restaurantes': '601.90.01',
        'honorarios': '601.88.01',
        'regalias': '601.74.01',
        'asistencia tecnica': '601.97.01',
        'seguros y fianzas': '601.98.01',
        'cuotas al imss': '601.26.01',
        'impuestos locales': '601.58.01',
        'adquisicion de mercancias': '501.01.01',
        'combustibles y lubricantes': '602.03.01',
        'uso o goce temporal de bienes': '602.09.01',
        'publicidad y propaganda': '601.89.01',
        'otros gastos': '601.84.01',
    }

    def _normalize_text(self, value):
        text = (value or '').strip().lower()
        text = ''.join(
            ch for ch in unicodedata.normalize('NFKD', text)
            if not unicodedata.combining(ch)
        )
        return ' '.join(text.split())

    def _normalize_vat(self, vat):
        raw = (vat or '').strip().upper().replace(' ', '').replace('-', '')
        if not raw:
            return raw
        # Keep explicit country-prefixed VATs untouched.
        if raw.startswith('MX') and len(raw) > 2:
            return raw
        # Mexican RFC without country prefix -> expected by Odoo as MX + RFC.
        if raw.isalnum() and len(raw) in (12, 13):
            return f"MX{raw}"
        if len(raw) >= 2 and raw[:2].isalpha():
            return raw
        return raw

    def _get_mx_country_id(self):
        country = request.env['res.country'].sudo().search([('code', '=', 'MX')], limit=1)
        return country.id if country else False

    def _extract_json_payload(self):
        try:
            raw = json.loads(request.httprequest.data.decode('utf-8'))
            return raw.get('params', raw)
        except Exception:
            return {}

    def _extract_uuid_value(self, data):
        value = (
            (data or {}).get('l10n_mx_edi_cfdi_uuid')
            or (data or {}).get('uuid')
            or (data or {}).get('folio_fiscal')
            or ''
        )
        return str(value).strip().upper()

    def _extract_reference_value(self, data):
        value = (
            (data or {}).get('name')
            or (data or {}).get('ref')
            or (data or {}).get('invoice_name')
            or ''
        )
        return str(value).strip()

    def _find_move_by_reference(self, reference, allowed_move_types, allowed_states=None):
        account_move = request.env['account.move'].sudo()
        domain = [('move_type', 'in', allowed_move_types), ('ref', '=', reference)]
        if allowed_states:
            domain.append(('state', 'in', allowed_states))
        move = account_move.search(domain, limit=1)
        return account_move, move

    def _build_uuid_domain(self, account_move, uuid):
        uuid_filters = []
        if 'folio_fiscal' in account_move._fields:
            uuid_filters.append(('folio_fiscal', '=', uuid))
        if 'l10n_mx_edi_cfdi_uuid' in account_move._fields:
            uuid_filters.append(('l10n_mx_edi_cfdi_uuid', '=', uuid))

        if not uuid_filters:
            return None
        if len(uuid_filters) == 1:
            return uuid_filters
        return ['|', uuid_filters[0], uuid_filters[1]]

    def _find_move_by_uuid(self, uuid, allowed_move_types, allowed_states=None):
        account_move = request.env['account.move'].sudo()
        domain = [('move_type', 'in', allowed_move_types)]
        if allowed_states:
            domain.append(('state', 'in', allowed_states))

        uuid_domain = self._build_uuid_domain(account_move, uuid)
        if uuid_domain is None:
            return account_move, None

        domain += uuid_domain
        move = account_move.search(domain, limit=1)
        return account_move, move

    def _is_special_delete_category(self, move, category_value):
        if category_value and category_value.strip().lower() == self.SPECIAL_DELETE_CATEGORY:
            return True

        ref_value = (move.ref or '').strip().lower()
        return ref_value == self.SPECIAL_DELETE_CATEGORY

    def _set_record_to_draft(self, record):
        if hasattr(record, 'button_draft'):
            record.button_draft()
            return
        if hasattr(record, 'action_draft'):
            record.action_draft()
            return
        raise ValueError(f"Cannot set record {record._name}({record.id}) to draft.")

    def _is_sequence_chain_delete_error(self, error):
        message = str(error or '').lower()
        return (
            'sequence' in message and 'last' in message and 'chain' in message
        ) or (
            'número de secuencia' in message and 'no es el último' in message
        ) or (
            'debe revertirlo' in message
        )

    def _reverse_move(self, move, reason):
        reversal_model = request.env['account.move.reversal'].sudo()
        reversal_ctx = dict(request.env.context, active_model='account.move', active_ids=move.ids)
        reversal_vals = {
            'date': fields.Date.context_today(request.env.user),
            'reason': reason,
        }
        if 'journal_id' in reversal_model._fields:
            reversal_vals['journal_id'] = move.journal_id.id

        reversal = reversal_model.with_context(reversal_ctx).create(reversal_vals)
        reversal.reverse_moves()

        if 'new_move_ids' in reversal._fields:
            return reversal.new_move_ids
        return request.env['account.move'].sudo().browse()

    def _get_related_payments(self, move):
        move_lines = move.line_ids
        partials = (move_lines.matched_debit_ids | move_lines.matched_credit_ids)
        counterpart_lines = (partials.debit_move_id | partials.credit_move_id) - move_lines

        payment_moves = counterpart_lines.mapped('move_id')
        payments = request.env['account.payment'].sudo().browse()

        # Some Odoo versions expose payment_id directly on account.move.
        if 'payment_id' in payment_moves._fields:
            payments |= payment_moves.mapped('payment_id')

        # Fallback compatible path: account.payment has move_id pointing to the payment move.
        if payment_moves:
            payments |= request.env['account.payment'].sudo().search([
                ('move_id', 'in', payment_moves.ids)
            ])

        return payments

    def _get_payment_related_documents(self, payment):
        payment_lines = payment.move_id.line_ids
        partials = (payment_lines.matched_debit_ids | payment_lines.matched_credit_ids)
        counterpart_lines = (partials.debit_move_id | partials.credit_move_id) - payment_lines
        return counterpart_lines.mapped('move_id').filtered(
            lambda m: m.move_type in ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')
        )

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
            seen_references = set()
            for bill_data in bills:
                try:
                    with request.env.cr.savepoint():
                        reference = self._extract_reference_value(bill_data)
                        if reference:
                            if reference in seen_references:
                                errors.append({
                                    'bill_data': bill_data,
                                    'error': f"Duplicate reference in request payload: '{reference}'",
                                })
                                continue

                            requested_move_type = bill_data.get('move_type')
                            allowed_move_types = [requested_move_type] if requested_move_type else ['in_invoice', 'in_refund']
                            _, existing_move = self._find_move_by_reference(
                                reference=reference,
                                allowed_move_types=allowed_move_types,
                            )
                            if existing_move:
                                errors.append({
                                    'bill_data': bill_data,
                                    'error': f"Duplicate reference already exists on move id={existing_move.id}: '{reference}'",
                                })
                                continue
                            seen_references.add(reference)

                        cfdi_uuid = self._extract_uuid_value(bill_data)

                        raw_vat = (bill_data.get('partner_id') or {}).get('vat', '')
                        normalized_vat = self._normalize_vat(raw_vat)
                        partner_name = (bill_data.get('partner_id') or {}).get('name')
                        mx_country_id = self._get_mx_country_id()
                        partner_model = request.env['res.partner'].sudo().with_context(no_vat_validation=True)

                        partner = partner_model.search([
                            ('name', '=', partner_name),
                            ('vat', 'in', [normalized_vat, raw_vat]),
                        ], limit=1)
                        if not partner and partner_name:
                            partner = partner_model.search([('name', '=', partner_name)], limit=1)
                        if not partner:
                            partner_vals = {
                                'name': partner_name,
                                'vat': normalized_vat,
                                'supplier_rank': 1,
                            }
                            if mx_country_id:
                                partner_vals['country_id'] = mx_country_id
                            partner = partner_model.create(partner_vals)
                        else:
                            update_vals = {}
                            if normalized_vat and partner.vat != normalized_vat:
                                update_vals['vat'] = normalized_vat
                            if mx_country_id and not partner.country_id:
                                update_vals['country_id'] = mx_country_id
                            if update_vals:
                                partner_model.browse(partner.id).write(update_vals)

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
                            'l10n_mx_edi_cfdi_uuid': cfdi_uuid,
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
                        if cfdi_uuid:
                            bill.sudo().write({'l10n_mx_edi_cfdi_uuid': cfdi_uuid})
                        _logger.info(f"Created bill {bill.id} for {partner_name}")
                except Exception as e:
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
            seen_references = set()
            for invoice_data in invoices:
                try:
                    with request.env.cr.savepoint():
                        reference = self._extract_reference_value(invoice_data)
                        if reference:
                            if reference in seen_references:
                                errors.append({
                                    'invoice_data': invoice_data,
                                    'error': f"Duplicate reference in request payload: '{reference}'",
                                })
                                continue

                            requested_move_type = invoice_data.get('move_type')
                            allowed_move_types = [requested_move_type] if requested_move_type else ['out_invoice', 'out_refund']
                            _, existing_move = self._find_move_by_reference(
                                reference=reference,
                                allowed_move_types=allowed_move_types,
                            )
                            if existing_move:
                                errors.append({
                                    'invoice_data': invoice_data,
                                    'error': f"Duplicate reference already exists on move id={existing_move.id}: '{reference}'",
                                })
                                continue
                            seen_references.add(reference)

                        cfdi_uuid = self._extract_uuid_value(invoice_data)

                        raw_vat = (invoice_data.get('partner_id') or {}).get('vat', '')
                        normalized_vat = self._normalize_vat(raw_vat)
                        partner_name = (invoice_data.get('partner_id') or {}).get('name')
                        mx_country_id = self._get_mx_country_id()
                        partner_model = request.env['res.partner'].sudo().with_context(no_vat_validation=True)

                        partner = partner_model.search([
                            ('name', '=', partner_name),
                            ('vat', 'in', [normalized_vat, raw_vat]),
                        ], limit=1)
                        if not partner and partner_name:
                            partner = partner_model.search([('name', '=', partner_name)], limit=1)
                        if not partner:
                            partner_vals = {
                                'name': partner_name,
                                'vat': normalized_vat,
                                'customer_rank': 1,
                            }
                            if mx_country_id:
                                partner_vals['country_id'] = mx_country_id
                            partner = partner_model.create(partner_vals)
                        else:
                            update_vals = {}
                            if normalized_vat and partner.vat != normalized_vat:
                                update_vals['vat'] = normalized_vat
                            if mx_country_id and not partner.country_id:
                                update_vals['country_id'] = mx_country_id
                            if update_vals:
                                partner_model.browse(partner.id).write(update_vals)

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
                            'l10n_mx_edi_cfdi_uuid': cfdi_uuid,
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

                        if cfdi_uuid:
                            invoice.sudo().write({'l10n_mx_edi_cfdi_uuid': cfdi_uuid})

                        _logger.info(f"Created invoice {invoice.id} for {partner_name}")
                except Exception as e:
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
                payload = self._extract_json_payload()

            uuid = uuid or payload.get('uuid') or payload.get('invoice_uuid')
            payment_data = payment_data or payload.get('payment_data', {})

            if not uuid:
                return {'error': 'Missing uuid (or invoice_uuid)'}
            if not payment_data:
                return {'error': 'Missing payment_data'}
            if not payment_data.get('journal_id'):
                return {'error': 'Missing payment_data.journal_id'}

            _, invoice = self._find_move_by_uuid(
                uuid=uuid,
                allowed_move_types=['out_invoice', 'out_refund'],
                allowed_states=['posted'],
            )
            if invoice is None:
                return {'error': 'No UUID field available on account.move (expected folio_fiscal or l10n_mx_edi_cfdi_uuid).'}
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

    @http.route('/api/delete_document_by_uuid', type='json', auth='public', methods=['POST'], csrf=False)
    def delete_document_by_uuid(self, uuid=None, document_type=None, **kwargs):
        try:
            payload = {}
            if not uuid or not document_type:
                payload = self._extract_json_payload()

            uuid = uuid or payload.get('uuid')
            document_type = (document_type or payload.get('document_type') or payload.get('type') or '').strip().lower()

            if not uuid:
                return {'error': 'Missing uuid'}
            if document_type not in ('invoice', 'bill'):
                return {'error': "Invalid type. Expected 'invoice' or 'bill'."}

            move_type_by_doc = {
                'invoice': ['out_invoice', 'out_refund'],
                'bill': ['in_invoice', 'in_refund'],
            }

            _, move = self._find_move_by_uuid(
                uuid=uuid,
                allowed_move_types=move_type_by_doc[document_type],
                allowed_states=['draft', 'posted'],
            )
            if move is None:
                return {'error': 'No UUID field available on account.move (expected folio_fiscal or l10n_mx_edi_cfdi_uuid).'}
            if not move:
                return {'error': f"No {document_type} found for UUID '{uuid}'"}

            payments = self._get_related_payments(move)
            deleted_payment_ids = []

            for payment in payments:
                related_docs = self._get_payment_related_documents(payment)
                linked_other_docs = related_docs.filtered(lambda doc: doc.id != move.id)
                if linked_other_docs:
                    return {
                        'error': (
                            f"Payment {payment.id} is reconciled with other documents "
                            f"({', '.join(linked_other_docs.mapped('name'))}). "
                            "Unlink it manually before deleting this document."
                        )
                    }

                if payment.move_id.line_ids:
                    payment.move_id.line_ids.remove_move_reconcile()

                payment_id = payment.id
                if payment.state == 'posted':
                    self._set_record_to_draft(payment)

                try:
                    payment.unlink()
                    deleted_payment_ids.append(payment_id)
                except Exception as payment_unlink_error:
                    if not self._is_sequence_chain_delete_error(payment_unlink_error):
                        raise
                    return {
                        'error': (
                            f"Payment {payment_id} cannot be deleted due to sequence chain rules. "
                            "It was set to draft, but Odoo still blocks deletion."
                        ),
                        'details': str(payment_unlink_error),
                    }

            if move.line_ids:
                move.line_ids.remove_move_reconcile()

            deleted_move_id = move.id
            deleted_move_name = move.name
            if move.state == 'posted':
                self._set_record_to_draft(move)

            try:
                move.unlink()
            except Exception as move_unlink_error:
                if not self._is_sequence_chain_delete_error(move_unlink_error):
                    raise
                return {
                    'error': (
                        f"{document_type.capitalize()} cannot be deleted due to sequence chain rules. "
                        "It was set to draft, but Odoo still blocks deletion."
                    ),
                    'details': str(move_unlink_error),
                }

            _logger.info(
                "Deleted %s %s (id=%s, uuid=%s) and related payments %s",
                document_type,
                deleted_move_name,
                deleted_move_id,
                uuid,
                deleted_payment_ids,
            )

            return {
                'success': f"{document_type.capitalize()} and related payments deleted",
                'uuid': uuid,
                'deleted_document_id': deleted_move_id,
                'deleted_payment_ids': deleted_payment_ids,
            }
        except Exception as e:
            request.env.cr.rollback()
            _logger.error("Failed to delete document by UUID: %s", str(e), exc_info=True)
            return {
                'error': 'Failed to delete document',
                'details': str(e)
            }

     # ---------- helpers ----------
    
    
    def _extract_payload_any(self):
        payload = {}
        try:
            raw = request.httprequest.data
            if raw:
                payload = json.loads(raw.decode("utf-8"))
                if isinstance(payload, dict) and "params" in payload and isinstance(payload["params"], dict):
                    payload = payload["params"]
        except Exception:
            payload = {}
        try:
            for k, v in (request.params or {}).items():
                payload.setdefault(k, v)
        except Exception:
            pass
        return payload or {}

    def _parse_limit(self, value, fallback=None):
        value = fallback if value is None else value
        if value in (None, "", False):
            return None
        try:
            parsed = int(value)
        except Exception:
            return None
        return parsed if parsed > 0 else None

    def _is_db_cursor_closed_error(self, err):
        msg = str(err or "").lower()
        return "cursor already closed" in msg or "connection already closed" in msg

    @http.route('/api/delete_all_bills_and_payments', type='json', auth='public', methods=['POST'], csrf=False)
    def delete_all_bills_and_payments(self, limit=None, limit_payments=None, limit_bills=None, **kwargs):
        try:
            payload = self._extract_payload_any()

            common_limit = self._parse_limit(limit, payload.get("limit"))
            payments_limit = self._parse_limit(limit_payments, payload.get("limit_payments")) or common_limit
            bills_limit = self._parse_limit(limit_bills, payload.get("limit_bills")) or common_limit

            Move = request.env["account.move"].sudo()
            Payment = request.env["account.payment"].sudo()

            # --- pick records ---
            payment_ids = Payment.search([], limit=payments_limit).ids
            bill_ids = Move.search([("move_type", "in", ["in_invoice", "in_refund"])], limit=bills_limit).ids

            total_payments = len(payment_ids)
            total_bills = len(bill_ids)

            deleted_payments = 0
            deleted_payment_moves = 0
            deleted_bills = 0
            sql_deleted_payments = 0

            errors = []
            fatal_db_error = None

            # --- helper: hard-delete payment + its move ---
            def _hard_delete_payment(pid: int):
                nonlocal deleted_payment_moves, sql_deleted_payments

                # Read minimal info without triggering heavy logic
                rec = Payment.browse(pid).exists()
                if not rec:
                    return

                move_id = rec.move_id.id if getattr(rec, "move_id", False) else None

                # 1) remove reconcile + delete move (if exists)
                if move_id:
                    m = Move.browse(move_id).exists().with_context(
                        force_delete=True,
                        check_move_validity=False,
                    )
                    if m:
                        if m.line_ids:
                            m.line_ids.remove_move_reconcile()
                        m.unlink()
                        deleted_payment_moves += 1

                # 2) SQL delete payment row (bypasses unlink validations)
                request.env.cr.execute("DELETE FROM account_payment WHERE id = %s", (pid,))
                if request.env.cr.rowcount:
                    sql_deleted_payments += 1

            # --- delete payments first ---
            for pid in payment_ids:
                try:
                    with request.env.cr.savepoint():
                        # Try normal unlink first (works for healthy payments)
                        p = Payment.browse(pid).exists().with_context(
                            force_delete=True,
                            check_move_validity=False,
                            skip_account_move_synchronization=True,
                        )
                        if not p:
                            continue
                        p.unlink()
                    deleted_payments += 1

                except Exception as err:
                    # If it is the known broken-payment error, fallback to hard-delete
                    msg = str(err or "")
                    if "No es posible confirmar un pago" in msg:
                        try:
                            with request.env.cr.savepoint():
                                _hard_delete_payment(pid)
                            deleted_payments += 1
                            continue
                        except Exception as hard_err:
                            errors.append({"model": "account.payment", "id": pid, "error": f"hard-delete failed: {hard_err}"})
                    else:
                        errors.append({"model": "account.payment", "id": pid, "error": msg})

                    if self._is_db_cursor_closed_error(err):
                        fatal_db_error = msg
                        break

            if fatal_db_error:
                return {
                    "error": "Bulk deletion interrupted by database cursor/connection closure",
                    "details": fatal_db_error,
                    "summary": {
                        "requested_limits": {"limit": common_limit, "limit_payments": payments_limit, "limit_bills": bills_limit},
                        "payments": {"found": total_payments, "deleted": deleted_payments, "sql_deleted": sql_deleted_payments},
                        "payment_moves_deleted": deleted_payment_moves,
                        "bills": {"found": total_bills, "deleted": deleted_bills},
                        "errors_count": len(errors),
                    },
                    "errors": errors,
                }

            # --- delete bills ---
            for bill_id in bill_ids:
                try:
                    with request.env.cr.savepoint():
                        b = Move.browse(bill_id).exists().with_context(
                            force_delete=True,
                            check_move_validity=False,
                        )
                        if not b:
                            continue
                        if b.line_ids:
                            b.line_ids.remove_move_reconcile()
                        b.unlink()
                    deleted_bills += 1
                except Exception as err:
                    errors.append({"model": "account.move", "id": bill_id, "error": str(err)})
                    if self._is_db_cursor_closed_error(err):
                        fatal_db_error = str(err)
                        break

            _logger.info(
                "Bulk delete finished. payments=%s/%s (sql=%s) payment_moves_deleted=%s bills=%s/%s errors=%s",
                deleted_payments, total_payments, sql_deleted_payments, deleted_payment_moves,
                deleted_bills, total_bills, len(errors)
            )

            return {
                "success": "Bulk deletion completed",
                "summary": {
                    "requested_limits": {"limit": common_limit, "limit_payments": payments_limit, "limit_bills": bills_limit},
                    "payments": {"found": total_payments, "deleted": deleted_payments, "sql_deleted": sql_deleted_payments},
                    "payment_moves_deleted": deleted_payment_moves,
                    "bills": {"found": total_bills, "deleted": deleted_bills},
                    "errors_count": len(errors),
                },
                "errors": errors,
            }

        except Exception as e:
            try:
                request.env.cr.rollback()
            except Exception:
                pass
            _logger.error("Failed bulk delete: %s", str(e), exc_info=True)
            return {"error": "Failed to bulk delete bills and payments", "details": str(e)}

    @http.route('/api/delete_all_bills_and_payments_http', type='http', auth='public', methods=['POST'], csrf=False)
    def delete_all_bills_and_payments_http(self, **kwargs):
        try:
            payload = self._extract_payload_any()
            res = self.delete_all_bills_and_payments(
                limit=payload.get("limit"),
                limit_payments=payload.get("limit_payments"),
                limit_bills=payload.get("limit_bills"),
            )
            # Catch late flush/commit issues as JSON
            request.env.cr.commit()
            return request.make_response(json.dumps(res), headers=[("Content-Type", "application/json")])
        except Exception as e:
            try:
                request.env.cr.rollback()
            except Exception:
                pass
            return request.make_response(
                json.dumps({"error": "HTTP bulk delete failed", "details": str(e)}),
                headers=[("Content-Type", "application/json")],
            )
        
    @http.route('/api/change_bill_account_by_uuid', type='json', auth='public', methods=['POST'], csrf=False)
    def change_bill_account_by_uuid(self, uuid=None, account=None, category=None, **kwargs):
        try:
            payload = {}
            if not uuid or (not account and not category):
                payload = self._extract_json_payload()

            uuid = uuid or payload.get('uuid')
            account = account or payload.get('account') or payload.get('account_name')
            category = category or payload.get('category')

            if not uuid:
                return {'error': 'Missing uuid'}
            if not category and not account:
                return {'error': 'Missing category (Nombre de la cuenta) or account (account_name)'}

            _, bill = self._find_move_by_uuid(
                uuid=uuid,
                allowed_move_types=['in_invoice', 'in_refund'],
                allowed_states=['draft', 'posted'],
            )
            if bill is None:
                return {'error': 'No UUID field available on account.move (expected folio_fiscal or l10n_mx_edi_cfdi_uuid).'}
            if not bill:
                return {'error': f"Bill not found for UUID '{uuid}'"}

            if self._is_special_delete_category(bill, category):
                return self.delete_document_by_uuid(uuid=uuid, document_type='bill')

            account_model = request.env['account.account'].sudo()
            matched_account_code = False
            if category:
                normalized_category = self._normalize_text(category)
                matched_account_code = self.CATEGORY_TO_ACCOUNT_CODE.get(normalized_category)
                if not matched_account_code:
                    return {
                        'error': (
                            f"Category '{category}' is not in the allowed catalog (Nombre de la cuenta)."
                        )
                    }

            target_account = account_model.browse()
            if matched_account_code:
                target_account = account_model.search([('code', '=', matched_account_code)], limit=1)

            if not target_account and account:
                target_account = account_model.search([('name', '=', account)], limit=1)
                if not target_account:
                    target_account = account_model.search([('name', 'ilike', account)], limit=1)
            if not target_account:
                if matched_account_code:
                    return {'error': f"Account with code '{matched_account_code}' not found"}
                return {'error': f"Account '{account}' not found"}
            if target_account.account_type in ('asset_receivable', 'liability_payable'):
                return {'error': f"Account '{target_account.name}' is receivable/payable and cannot be used in bill line items."}

            was_posted = bill.state == 'posted'
            if bill.line_ids:
                bill.line_ids.remove_move_reconcile()
            if was_posted:
                self._set_record_to_draft(bill)

            bill.invoice_line_ids.sudo().write({'account_id': target_account.id})

            if was_posted:
                bill.action_post()

            _logger.info(
                "Updated bill %s (id=%s, uuid=%s) line accounts to %s (%s)",
                bill.name,
                bill.id,
                uuid,
                target_account.name,
                target_account.id,
            )

            return {
                'success': 'Bill account updated',
                'uuid': uuid,
                'bill_id': bill.id,
                'account_id': target_account.id,
                'account_name': target_account.name,
                'account_code': target_account.code,
                'matched_category': category,
                'updated_line_ids': bill.invoice_line_ids.ids,
            }
        except Exception as e:
            request.env.cr.rollback()
            _logger.error("Failed to change bill account by UUID: %s", str(e), exc_info=True)
            return {
                'error': 'Failed to change bill account',
                'details': str(e)
            }

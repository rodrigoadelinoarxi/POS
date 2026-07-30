# -*- coding: utf-8 -*-
import json
import logging
import uuid
import requests
from odoo import api, fields, models

_logger = logging.getLogger(__name__)
DEFAULT_RECEIPT_URL = 'http://127.0.0.1:5000/print'
DEFAULT_BEVERAGES_URL = 'http://127.0.0.1:5000/print'
DEFAULT_TIMEOUT = 12


class PosPrintJob(models.Model):
    _name = 'pos.print.job'
    _description = 'Fila de Impressão POS'
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char(string='Job ID', required=True, copy=False, index=True,
                       default=lambda self: str(uuid.uuid4()))
    pos_order_id = fields.Many2one('pos.order', string='Encomenda POS', ondelete='cascade', index=True)
    pos_reference = fields.Char(string='Referência', related='pos_order_id.pos_reference', store=True)
    state = fields.Selection([
        ('pending', 'Pendente'), ('sent', 'Enviado'), ('accepted', 'Aceite'),
        ('printed', 'Impresso'), ('error', 'Erro')
    ], default='pending', required=True, copy=False, index=True)
    attempts = fields.Integer(default=0, copy=False)
    max_attempts = fields.Integer(default=5)
    job_type = fields.Selection([
        ('receipt', 'Talão'), ('kitchen', 'Bebidas')
    ], string='Tipo', default='receipt', required=True)
    payload = fields.Text(string='Conteúdo Enviado (JSON)')
    last_response = fields.Text(string='Última Resposta')
    last_error = fields.Text(string='Último Erro')

    @api.model
    def create_from_order(self, order, extra_payload=None, job_type='receipt'):
        payload = (self._build_beverages_payload(order) if job_type == 'kitchen'
                   else self._build_receipt_payload(order, extra_payload or {}))
        return self.create({
            'pos_order_id': order.id,
            'job_type': job_type,
            'payload': json.dumps(payload, default=str),
        })

    @api.model
    def _extract_order_number(self, reference):
        if not reference:
            return ''
        tail = reference.split('-')[-1]
        digits = ''.join(c for c in tail if c.isdigit())
        return digits[-3:] if len(digits) >= 3 else digits

    @api.model
    def _table_label(self, order):
        if 'table_id' not in order._fields or not order.table_id:
            return ''
        table = order.table_id
        floor = table.floor_id.name if table.floor_id else ''
        return f'{floor} - {table.name}' if floor else table.name

    def _base(self, order):
        return {
            'job_id': None,
            'order_ref': order.pos_reference or order.name,
            'order_number': self._extract_order_number(order.pos_reference or order.name),
            'table': self._table_label(order),
            'cashier': order.user_id.name if order.user_id else '',
            'date': fields.Datetime.to_string(order.date_order) if order.date_order else '',
        }

    def _build_beverages_payload(self, order):
        payload = self._base(order)
        payload.update({'document_type': 'beverages', 'lines': []})
        for line in order.lines:
            payload['lines'].append({
                'product': line.product_id.display_name,
                'qty': line.qty,
                'note': getattr(line, 'customer_note', '') or '',
            })
        return payload

    def _build_receipt_payload(self, order, frontend):
        company, partner = order.company_id, order.partner_id
        payload = self._base(order)
        payload.update({
            'document_type': 'receipt',
            'company': {
                'name': company.name or '', 'vat': company.vat or '',
                'street': company.street or '', 'street2': company.street2 or '',
                'city': company.city or '', 'zip': company.zip or '',
                'country': company.country_id.name if company.country_id else '',
                'phone': company.phone or '', 'email': company.email or '',
                'logo_base64': company.logo.decode() if company.logo else None,
            },
            'partner': {'name': partner.name or '', 'vat': partner.vat or ''} if partner else None,
            'lines': [],
            'amount_total': order.amount_total,
            'amount_tax': order.amount_tax,
            'amount_untaxed': order.amount_total - order.amount_tax,
            'payments': [], 'change': 0.0,
            'qr_code': None, 'atcud': None, 'hash_code': None,
        })
        for line in order.lines:
            payload['lines'].append({
                'product': line.product_id.display_name,
                'qty': line.qty, 'price_unit': line.price_unit,
                'discount': line.discount,
                'price_subtotal': line.price_subtotal,
                'price_subtotal_incl': line.price_subtotal_incl,
            })
        total_paid = sum(order.payment_ids.mapped('amount'))
        for payment in order.payment_ids.filtered(lambda p: p.amount > 0):
            payload['payments'].append({
                'method': payment.payment_method_id.name,
                'amount': payment.amount,
            })
        payload['change'] = max(round(total_paid - order.amount_total, 2), 0.0)
        # Apenas os dados fiscais capturados no ecrã podem sobrepor estes campos.
        for key in ('qr_code', 'atcud', 'hash_code'):
            if frontend.get(key) is not None:
                payload[key] = frontend[key]
        return payload

    def action_send(self):
        icp = self.env['ir.config_parameter'].sudo()
        for job in self:
            if job.job_type == 'kitchen':
                url = icp.get_param('pos_hprt_printer.beverages_url', DEFAULT_BEVERAGES_URL)
                token = icp.get_param('pos_hprt_printer.beverages_token', '')
            else:
                url = icp.get_param('pos_hprt_printer.receipt_url', DEFAULT_RECEIPT_URL)
                token = icp.get_param('pos_hprt_printer.receipt_token', '')
            if not token:
                job.write({'state': 'error', 'last_error': 'Token não configurado nos Parâmetros do Sistema.'})
                continue
            body = json.loads(job.payload or '{}')
            body['job_id'] = job.name
            job.attempts += 1
            try:
                response = requests.post(url, json=body, headers={'X-Print-Token': token}, timeout=DEFAULT_TIMEOUT)
                job.last_response = (response.text or '')[:4000]
                if response.status_code == 200:
                    result = response.json() if response.content else {}
                    job.state = 'printed' if result.get('status') in ('printed', 'duplicate') else 'sent'
                    job.last_error = False
                else:
                    job.last_error = f'HTTP {response.status_code}: {(response.text or "")[:500]}'
                    job.state = 'error' if job.attempts >= job.max_attempts else 'pending'
            except requests.RequestException as exc:
                job.last_error = str(exc)
                job.state = 'error' if job.attempts >= job.max_attempts else 'pending'
        return True

    def action_reprint(self):
        new_jobs = self.env['pos.print.job']
        for job in self:
            new_jobs |= self.create({
                'pos_order_id': job.pos_order_id.id,
                'job_type': job.job_type,
                'payload': job.payload,
            })
        new_jobs.action_send()
        return True

    @api.model
    def _cron_retry_pending(self):
        jobs = self.search([('state', 'in', ['pending', 'error'])]).filtered(
            lambda j: j.attempts < j.max_attempts
        )
        if jobs:
            jobs.action_send()

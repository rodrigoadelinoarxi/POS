# -*- coding: utf-8 -*-
import json
import logging
import uuid

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Valores por omissão, sobrepostos pelos Parâmetros do Sistema
# (Definições Técnicas > Parâmetros > Parâmetros do Sistema):
#   pos_hprt_printer.url    -> http://100.109.78.81:5000/print
#   pos_hprt_printer.token  -> token secreto (X-Print-Token)
DEFAULT_PRINT_URL = 'http://100.109.78.81:5000/print'
DEFAULT_TIMEOUT = 8  # segundos


class PosPrintJob(models.Model):
    _name = 'pos.print.job'
    _description = 'Fila de Impressão POS -> HPRT (Raspberry)'
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Job ID', required=True, copy=False, index=True,
        default=lambda self: str(uuid.uuid4()),
    )
    pos_order_id = fields.Many2one(
        'pos.order', string='Encomenda POS', ondelete='cascade', index=True,
    )
    pos_reference = fields.Char(string='Referência', related='pos_order_id.pos_reference', store=True)
    state = fields.Selection(
        [
            ('pending', 'Pendente'),
            ('sent', 'Enviado'),
            ('accepted', 'Aceite'),
            ('printed', 'Impresso'),
            ('error', 'Erro'),
        ],
        string='Estado', default='pending', required=True, copy=False, index=True,
    )
    attempts = fields.Integer(string='Tentativas', default=0, copy=False)
    max_attempts = fields.Integer(string='Máx. Tentativas', default=5)
    payload = fields.Text(string='Conteúdo Enviado (JSON)')
    last_response = fields.Text(string='Última Resposta')
    last_error = fields.Text(string='Último Erro')

    # ------------------------------------------------------------------
    # Criação a partir dos dados de uma encomenda POS
    # ------------------------------------------------------------------
    @api.model
    def create_from_order(self, order, extra_payload=None):
        """Cria um job novo (com job_id novo) para a encomenda `order`
        (recordset pos.order de 1 registo) e devolve o job criado.
        `extra_payload` pode conter dados já montados no frontend
        (linhas, totais) para não dependermos de re-ler tudo do ORM.
        """
        payload_dict = self._build_payload(order, extra_payload=extra_payload)
        job = self.create({
            'pos_order_id': order.id if order else False,
            'payload': json.dumps(payload_dict, default=str),
        })
        return job

    def _build_payload(self, order, extra_payload=None):
        self.ensure_one() if False else None  # noop, mantém assinatura clara
        company = order.company_id if order else self.env.company
        partner = order.partner_id if order else False

        payload = {
            'job_id': None,  # preenchido depois de criar o registo (self.name)
            'order_ref': order.pos_reference or order.name if order else False,
            'date': fields.Datetime.to_string(order.date_order) if order and order.date_order else False,
            'company': {
                'name': company.name,
                'vat': company.vat or '',
                'street': company.street or '',
                'street2': company.street2 or '',
                'city': company.city or '',
                'zip': company.zip or '',
                'country': company.country_id.name if company.country_id else '',
                'phone': company.phone or '',
                'email': company.email or '',
            },
            'partner': {
                'name': partner.name,
                'vat': partner.vat or '',
            } if partner else None,
            'lines': [],
            'amount_total': order.amount_total if order else 0.0,
            'amount_tax': order.amount_tax if order else 0.0,
            'payments': [],
        }

        if order:
            for line in order.lines:
                payload['lines'].append({
                    'product': line.product_id.display_name,
                    'qty': line.qty,
                    'price_unit': line.price_unit,
                    'discount': line.discount,
                    'price_subtotal_incl': line.price_subtotal_incl,
                })
            for pay in order.payment_ids:
                payload['payments'].append({
                    'method': pay.payment_method_id.name,
                    'amount': pay.amount,
                })

        # Se o frontend já enviou os dados construídos (mais fiável,
        # porque reflete exatamente o que está no ecrã de recibo),
        # sobrepomos os campos correspondentes.
        if extra_payload:
            payload.update({k: v for k, v in extra_payload.items() if v is not None})

        return payload

    # ------------------------------------------------------------------
    # Envio para o Raspberry
    # ------------------------------------------------------------------
    def action_send(self):
        icp = self.env['ir.config_parameter'].sudo()
        url = icp.get_param('pos_hprt_printer.url', DEFAULT_PRINT_URL)
        token = icp.get_param('pos_hprt_printer.token', '')

        if not token:
            _logger.warning(
                'pos_hprt_printer: parâmetro de sistema "pos_hprt_printer.token" '
                'não está definido. Configure-o em Definições Técnicas > Parâmetros.'
            )

        for job in self:
            if job.attempts >= job.max_attempts and job.state == 'error':
                continue

            payload_dict = json.loads(job.payload or '{}')
            payload_dict['job_id'] = job.name
            body = json.dumps(payload_dict, default=str)

            job.attempts += 1
            try:
                resp = requests.post(
                    url,
                    data=body,
                    headers={
                        'Content-Type': 'application/json',
                        'X-Print-Token': token,
                    },
                    timeout=DEFAULT_TIMEOUT,
                )
                job.last_response = (resp.text or '')[:4000]

                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except ValueError:
                        data = {}
                    status = data.get('status')
                    if status == 'printed':
                        job.state = 'printed'
                    elif status == 'accepted':
                        job.state = 'accepted'
                    elif status == 'duplicate':
                        # já tinha sido impresso antes (job_id repetido)
                        job.state = 'printed'
                    else:
                        job.state = 'sent'
                    job.last_error = False
                else:
                    job.last_error = 'HTTP %s' % resp.status_code
                    job.state = 'error' if job.attempts >= job.max_attempts else 'pending'

            except requests.exceptions.RequestException as exc:
                _logger.warning('pos_hprt_printer: falha ao enviar job %s: %s', job.name, exc)
                job.last_error = str(exc)
                job.state = 'error' if job.attempts >= job.max_attempts else 'pending'

        return True

    def action_reprint(self):
        """Cria um NOVO job (com job_id novo) com o mesmo conteúdo, para
        reimpressão manual, sem ficar bloqueado pela deduplicação de
        job_id no Raspberry."""
        new_jobs = self.env['pos.print.job']
        for job in self:
            payload_dict = json.loads(job.payload or '{}')
            new_job = self.create({
                'pos_order_id': job.pos_order_id.id,
                'payload': json.dumps(payload_dict, default=str),
            })
            new_jobs |= new_job
        new_jobs.action_send()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Reimpressão',
                'message': 'Pedido de reimpressão enviado (%s job(s)).' % len(new_jobs),
                'type': 'success',
            },
        }

    @api.model
    def _cron_retry_pending(self):
        """Corrido periodicamente (ver data/ir_cron.xml) para reenviar
        jobs pendentes ou com erro, respeitando o limite de tentativas."""
        jobs = self.search([('state', 'in', ['pending', 'error'])])
        jobs = jobs.filtered(lambda j: j.attempts < j.max_attempts)
        if jobs:
            _logger.info('pos_hprt_printer: cron a reenviar %s job(s) pendente(s)', len(jobs))
            jobs.action_send()

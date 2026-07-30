# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class PosHprtPrinterController(http.Controller):

    @http.route('/pos_hprt_printer/print_receipt', type='json', auth='user', csrf=False)
    def print_receipt(self, order_id=None, receipt=None, **kwargs):
        """Chamado pelo JS do POS (patch ao ReceiptScreen.printReceipt).

        - order_id: id do pos.order já sincronizado no servidor.
        - receipt: dicionário já construído no frontend com os dados
          exatamente como aparecem no ecrã de recibo (linhas, totais,
          pagamentos, cliente). Usado para não depender de detalhes
          internos do ORM que podem variar por instalação/versão.
        """
        order = request.env['pos.order'].browse(int(order_id)) if order_id else request.env['pos.order']
        if order_id and not order.exists():
            _logger.warning('pos_hprt_printer: pos.order %s não encontrado no servidor', order_id)
            order = request.env['pos.order']

        job = request.env['pos.print.job'].sudo().create_from_order(order, extra_payload=receipt)
        job.action_send()

        return {
            'job_id': job.name,
            'state': job.state,
            'last_error': job.last_error or False,
        }

    @http.route('/pos_hprt_printer/send_to_kitchen', type='json', auth='user', csrf=False)
    def send_to_kitchen(self, order_id=None, **kwargs):
        """Chamado pelo botão 'Enviar para a Cozinha'. Monta um talão
        simplificado (só quem atendeu, número do pedido, e produtos
        com quantidade) e envia para a impressora da cozinha."""
        order = request.env['pos.order'].browse(int(order_id)) if order_id else request.env['pos.order']
        if order_id and not order.exists():
            _logger.warning('pos_hprt_printer: pos.order %s não encontrado no servidor', order_id)
            order = request.env['pos.order']

        job = request.env['pos.print.job'].sudo().create_from_order(order, job_type='kitchen')
        job.action_send()

        return {
            'job_id': job.name,
            'state': job.state,
            'last_error': job.last_error or False,
        }

# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class PosHprtPrinterController(http.Controller):

    def _find_order(self, order_id=None, pos_reference=None):
        Order = request.env['pos.order'].sudo()
        if order_id:
            try:
                order = Order.browse(int(order_id)).exists()
                if order:
                    return order
            except (TypeError, ValueError):
                pass
        if pos_reference:
            order = Order.search([
                '|', ('pos_reference', '=', pos_reference), ('name', '=', pos_reference)
            ], limit=1, order='id desc')
            if order:
                return order
        return Order

    @http.route('/pos_hprt_printer/print_receipt', type='json', auth='user', csrf=False)
    def print_receipt(self, order_id=None, pos_reference=None, receipt=None, **kwargs):
        order = self._find_order(order_id, pos_reference)
        if not order:
            return {'state': 'error', 'last_error': 'Venda ainda não encontrada no servidor. Tente novamente.'}
        job = request.env['pos.print.job'].sudo().create_from_order(
            order, extra_payload=receipt or {}, job_type='receipt'
        )
        job.action_send()
        return {'job_id': job.name, 'state': job.state, 'last_error': job.last_error or False}

    @http.route('/pos_hprt_printer/print_beverages', type='json', auth='user', csrf=False)
    def print_beverages(self, order_id=None, pos_reference=None, **kwargs):
        order = self._find_order(order_id, pos_reference)
        if not order:
            return {'state': 'error', 'last_error': 'Venda ainda não encontrada no servidor. Tente novamente.'}
        job = request.env['pos.print.job'].sudo().create_from_order(order, job_type='kitchen')
        job.action_send()
        return {'job_id': job.name, 'state': job.state, 'last_error': job.last_error or False}

# -*- coding: utf-8 -*-
{
    'name': 'POS HPRT Printer (via Raspberry Pi + Tailscale)',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Envia o recibo do POS para uma impressora HPRT TP80K ligada a um Raspberry Pi via Tailscale',
    'description': """
Módulo de demonstração que intercepta o botão "Imprimir" do ecrã de
recibo do POS e envia os dados da venda (formatados como fatura, sem
gerar nenhum account.move oficial) para uma API Flask alojada num
Raspberry Pi, acessível através de uma rede privada Tailscale.

Inclui:
- Fila de impressão (pos.print.job) com estados: pendente, enviado, aceite, impresso, erro
- job_id único por pedido, para evitar impressões duplicadas
- Retentativas automáticas via cron, com limite de tentativas
- Reimpressão manual a partir do backend
- Histórico completo de pedidos de impressão
""",
    'author': 'Custom',
    'depends': ['point_of_sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/print_queue_views.xml',
        'data/ir_cron.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_hprt_printer/static/src/js/receipt_screen_patch.js',
            'pos_hprt_printer/static/src/xml/receipt_screen_patch.xml',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}

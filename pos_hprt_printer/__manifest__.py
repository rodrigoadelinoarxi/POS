# -*- coding: utf-8 -*-
{
    'name': 'POS Impressoras Externas - Talão e Bebidas',
    'version': '18.0.2.0.0',
    'category': 'Point of Sale',
    'summary': 'Talão fiscal no PC/AQPROX e tickets de bebidas no Raspberry/HPRT',
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

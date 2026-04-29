{
    'name': 'Custom Bill Receive',
    'version': '1.0',
    'depends': ['account'],
    'data': [
        'views/account_payment_views.xml',
        'views/account_move_line_views.xml',
    ],
    'installable': True,
    'application': False,
}

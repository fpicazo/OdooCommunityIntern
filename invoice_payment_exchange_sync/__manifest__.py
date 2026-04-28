{
    'name': 'Invoice Payment Exchange Sync',
    'version': '1.0',
    'summary': 'Register payments using the invoice exchange rate',
    'author': 'OpenAI',
    'category': 'Accounting',
    'depends': ['account'],
    'data': [
        'views/account_move_views.xml',
    ],
    'installable': True,
    'application': False,
}

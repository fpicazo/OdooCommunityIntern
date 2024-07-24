# invoice_button_draft/__manifest__.py
{
    'name': 'Custom Facturacion Mexicana',
    'version': '1.0',
    'summary': 'Facturacion Mexicana',
    'author': 'Flavien Picazo',
    'category': 'Accounting',
    'depends': ['account', 'product','project','sale','hr'],
    'data': [
        'views/res_partner_views.xml',
        'views/product_template_views.xml',
        'views/account_move_views.xml',
        'views/project_view.xml',
        'views/task_view.xml',
        'views/sale_order_view.xml',
        'views/hr_employee_view.xml',
    ],
    'installable': True,
    'application': False,
}

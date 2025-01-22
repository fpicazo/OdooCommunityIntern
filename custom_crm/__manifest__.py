{
    'name': 'Custom Quote Prefix by Unidad de Negocio',
    'version': '1.0',
    'category': 'Sales',
    'summary': 'Changes the quote prefix based on Unidad de Negocio',
    'description': """
    This module changes the prefix of the quote based on the selected Unidad de Negocio.
    """,
    'author': 'Your Name',
    'depends': ['sale'],
    'data': [
        'data/ir_sequence_data.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

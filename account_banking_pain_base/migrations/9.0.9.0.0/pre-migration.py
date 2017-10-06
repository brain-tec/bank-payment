# -*- coding: utf-8 -*-
# © 2015 Yannick Vaucher (Camptocamp SA)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""
The banks have been created with dumb xml ids.
Change xml ids to keep track of those bank with
http://www.six-interbank-clearing.com/ (see README.rst for source)
"""


def migrate(cr, version):
    if not version:
        return
    # HACK: 06.10.17 14:16: jool1: we needed to remove view from version 9.0 in order to make the module installable
    cr.execute("delete from ir_ui_view where name = 'pain.group.on.res.company.form';")
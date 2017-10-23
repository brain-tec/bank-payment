# -*- coding: utf-8 -*-

def migrate(cr, version):
    if not version:
        return
    # HACK: 06.10.17 14:16: jool1: we needed to remove view from version 9.0 in order to make the module installable
    cr.execute("delete from ir_ui_view where name = 'pain.group.on.res.company.form';")
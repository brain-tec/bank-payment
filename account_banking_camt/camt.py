# -*- coding: utf-8 -*-
"""Class to parse camt files."""
##############################################################################
#
#    Copyright (C) 2013-2015 Therp BV <http://therp.nl>
#    Copyright 2017 Open Net Sàrl
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published
#    by the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import re
from datetime import datetime
from lxml import etree
from openerp.addons.account_banking.parsers import models
from copy import copy


bt = models.mem_bank_transaction

class bank_transaction(models.mem_bank_transaction):

    def __init__(self, values, *args, **kwargs):
        super(bank_transaction, self).__init__(*args, **kwargs)
        for attr in values:
            setattr(self, attr, values[attr])
            if attr == 'amount' and not self.transferred_amount:
                setattr(self, 'transferred_amount', self.amount)
            elif attr == 'eref' and not self.reference:
                setattr(self, 'reference', self.eref)


    def is_valid(self):
        return (not self.error_message and self.execution_date and
                self.transferred_amount and True) or False


class CamtParser(models.parser):
    code = 'CAMT'
    country_code = 'CH'
    name = 'Generic CAMT Format'
    doc = '''\
    CAMT Format parser which supports camt.053 and camt.054
    '''
    """Parser for camt bank statement import files."""

    def parse_amount(self, ns, node):
        """Parse element that contains Amount and CreditDebitIndicator."""
        if node is None:
            return 0.0
        sign = 1
        amount = 0.0
        sign_node = node.xpath('ns:CdtDbtInd', namespaces={'ns': ns})
        if sign_node and sign_node[0].text == 'DBIT':
            sign = -1
        amount_node = node.xpath('ns:Amt', namespaces={'ns': ns})
        if amount_node:
            amount = sign * float(amount_node[0].text)
        return amount

    def add_value_from_node(
            self, ns, node, xpath_str, obj, attr_name, join_str=None):
        """Add value to object from first or all nodes found with xpath.

        If xpath_str is a list (or iterable), it will be seen as a series
        of search path's in order of preference. The first item that results
        in a found node will be used to set a value."""
        if not isinstance(xpath_str, (list, tuple)):
            xpath_str = [xpath_str]
        for search_str in xpath_str:
            found_node = node.xpath(search_str, namespaces={'ns': ns})
            if found_node:
                if join_str is None:
                    attr_value = found_node[0].text
                else:
                    attr_value = join_str.join([x.text for x in found_node])
                # HACK by BT-mgerecke
                # Use setattr not on dict-objects.
                if isinstance(obj, dict):
                    obj[attr_name] = attr_value
                else:
                    setattr(obj, attr_name, attr_value)
                # End Hack
                break

    def parse_transaction_details(self, ns, node, transaction):
        """Parse TxDtls node."""
        # message
        self.add_value_from_node(
            ns, node, [
                './ns:RmtInf/ns:Ustrd',
                './ns:AddtlTxInf',
                './ns:AddtlNtryInf',
            ], transaction, 'message', join_str='\n')
        # eref
        self.add_value_from_node(
            ns, node, [
                './ns:RmtInf/ns:Strd/ns:CdtrRefInf/ns:Ref',
                './ns:Refs/ns:EndToEndId',
            ],
            transaction, 'eref'
        )
        amount = self.parse_amount(ns, node)
        if amount != 0.0:
            transaction['amount'] = amount
        # remote party values
        party_type = 'Dbtr'
        party_type_node = node.xpath(
            '../../ns:CdtDbtInd', namespaces={'ns': ns})
        if party_type_node and party_type_node[0].text != 'CRDT':
            party_type = 'Cdtr'
        party_node = node.xpath(
            './ns:RltdPties/ns:%s' % party_type, namespaces={'ns': ns})
        if party_node:
            self.add_value_from_node(
                ns, party_node[0], './ns:Nm', transaction, 'remote_owner')
            self.add_value_from_node(
                ns, party_node[0], './ns:PstlAdr/ns:Ctry', transaction,
                'remote_owner_country'
            )
            address_node = party_node[0].xpath(
                './ns:PstlAdr/ns:AdrLine', namespaces={'ns': ns})
            if address_node:
                transaction['remote_owner_address'] = address_node
        # Get remote_account from iban or from domestic account:
        account_node = node.xpath(
            './ns:RltdPties/ns:%sAcct/ns:Id' % party_type,
            namespaces={'ns': ns}
        )
        if account_node:
            iban_node = account_node[0].xpath(
                './ns:IBAN', namespaces={'ns': ns})
            if iban_node:
                transaction['remote_account'] = iban_node[0].text
                bic_node = node.xpath(
                    './ns:RltdAgts/ns:%sAgt/ns:FinInstnId/ns:BIC' % party_type,
                    namespaces={'ns': ns}
                )
                if bic_node:
                    transaction['remote_bank_bic'] = bic_node[0].text
            else:
                self.add_value_from_node(
                    ns, account_node[0], './ns:Othr/ns:Id', transaction,
                    'remote_account'
                )

    def parse_entry(self, ns, node, local_account):
        """Parse an Ntry node and yield transactions."""
        transaction_base = {}
        transaction_base['local_account'] = local_account
        self.add_value_from_node(
            ns, node, './ns:BkTxCd/ns:Prtry/ns:Cd', transaction_base,
            'transfer_type'
        )
        #TODO by BT_mgerecke
        self.add_value_from_node(
            ns, node, './ns:BookgDt/ns:Dt', transaction_base, 'date')
        self.add_value_from_node(
            ns, node, './ns:BookgDt/ns:Dt', transaction_base, 'execution_date')
        self.add_value_from_node(
            ns, node, './ns:ValDt/ns:Dt', transaction_base, 'value_date')
        amount = self.parse_amount(ns, node)
        if amount != 0.0:
            transaction_base['amount'] = amount
        self.add_value_from_node(
            ns, node, './ns:AddtlNtryInf', transaction_base, 'name')
        self.add_value_from_node(
            ns, node, [
                './ns:NtryDtls/ns:RmtInf/ns:Strd/ns:CdtrRefInf/ns:Ref',
                './ns:NtryDtls/ns:Btch/ns:PmtInfId',
            ],
            transaction_base, 'ref'
        )
        details_nodes = node.xpath(
            './ns:NtryDtls/ns:TxDtls', namespaces={'ns': ns})
        if len(details_nodes) == 0:
            return self.get_real_transaction_from_data(transaction_base)
        transactions = []
        for i, dnode in enumerate(details_nodes):
            transaction_data = copy(transaction_base)
            self.parse_transaction_details(ns, dnode, transaction_data)
            # transactions['data'] should be a synthetic xml snippet which
            # contains only the TxDtls that's relevant.
            data = copy(node)
            for j, dnode in enumerate(data.xpath(
                    './ns:NtryDtls/ns:TxDtls', namespaces={'ns': ns})):
                if j != i:
                    dnode.getparent().remove(dnode)
            transaction_data['data'] = etree.tostring(data)
            #TODO by BT_mgerecke
            # Put all known parameter into the transaction object.
            transactions.append(bank_transaction(transaction_data))
        return transactions

    def get_balance_amounts(self, ns, node):
        """Return opening and closing balance.

        Depending on kind of balance and statement, the balance might be in a
        different kind of node:
        OPBD = OpeningBalance
        PRCD = PreviousClosingBalance
        ITBD = InterimBalance (first ITBD is start-, second is end-balance)
        CLBD = ClosingBalance
        """
        start_balance_node = None
        end_balance_node = None
        for node_name in ['OPBD', 'PRCD', 'CLBD', 'ITBD']:
            code_expr = (
                './ns:Bal/ns:Tp/ns:CdOrPrtry/ns:Cd[text()="%s"]/../../..' %
                node_name
            )
            balance_node = node.xpath(code_expr, namespaces={'ns': ns})
            if balance_node:
                if node_name in ['OPBD', 'PRCD']:
                    start_balance_node = balance_node[0]
                elif node_name == 'CLBD':
                    end_balance_node = balance_node[0]
                else:
                    if not start_balance_node:
                        start_balance_node = balance_node[0]
                    if not end_balance_node:
                        end_balance_node = balance_node[-1]
        return (
            self.parse_amount(ns, start_balance_node),
            self.parse_amount(ns, end_balance_node)
        )

    def parse_statement(self, ns, node):
        """Parse a single Stmt node."""
        statement = models.mem_bank_statement()
        self.add_value_from_node(
            ns, node, [
                './ns:Acct/ns:Id/ns:IBAN',
                './ns:Acct/ns:Id/ns:Othr/ns:Id',
            ], statement, 'local_account'
        )
        self.add_value_from_node(
            ns, node, './ns:Id', statement, 'id')
        # Fill statement name otherwise it will be a number.
        self.add_value_from_node(
            ns, node, './ns:Acct/ns:Ccy', statement, 'local_currency')
        (statement.start_balance, statement.end_balance) = (
            self.get_balance_amounts(ns, node))
        entry_nodes = node.xpath('./ns:Ntry', namespaces={'ns': ns})
        transactions = []
        stmt_number = 0
        for entry_node in entry_nodes:
            # TODO
            # Multiple Statements per File are created as transactions but not as statements.
            statement.transactions.extend(self.parse_entry(ns, entry_node, statement.local_account))
        if statement.transactions:
            execution_date = statement.transactions[0].execution_date[:10]
            # TODO by BT_mgerecke
            # Date may also be stored without "-" in statement.id
            statement.date = datetime.strptime(execution_date, "%Y-%m-%d")
            # Prepend date of first transaction to improve id uniquenes
            if execution_date not in statement.id:
                statement.id = "%s-%s" % (
                    execution_date, statement.id)

            # TODO
            # HACK by BT-mgerecke for camt.054
            # Sum-up transaction amounts for a sane end_balance.
            trns_number = 0
            end_balance = 0
            for trans in statement.transactions:
                transferred_amount = trans.transferred_amount
                #if camt_version == 54 and statement.transactions.transferred_amount:
                if transferred_amount:
                    end_balance += transferred_amount
                trans.id = str(trns_number).zfill(4)
                trns_number += 1
            # End Hack
            stmt_number += 1
            statement.id = str(stmt_number).zfill(4)
            if statement.end_balance != 0.0 and statement.end_balance != end_balance:
                raise ValueError('expected end-balance ' + statement.end_balance + ' not met, got: ' + end_balance)
            else:
                statement.end_balance = end_balance
        return statement

    def check_version(self, ns, root):
        """Validate validity of camt file."""
        # Check wether it is camt at all:
        re_camt = re.compile(
            r'(^urn:iso:std:iso:20022:tech:xsd:camt.'
            r'|^ISO:camt.)'
        )
        if not re_camt.search(ns):
            raise ValueError('no camt: ' + ns)
        # Check wether version 052 ,053 or 054:
        re_camt_version = re.compile(
            r'(^urn:iso:std:iso:20022:tech:xsd:camt.054.'
            r'|^urn:iso:std:iso:20022:tech:xsd:camt.053.'
            r'|^urn:iso:std:iso:20022:tech:xsd:camt.052.'
            r'|^ISO:camt.054.'
            r'|^ISO:camt.053.'
            r'|^ISO:camt.052.)'
        )
        if not re_camt_version.search(ns):
            raise ValueError('no camt 052 or 053: ' + ns)
        # Check GrpHdr element:
        root_0_0 = root[0][0].tag[len(ns) + 2:]  # strip namespace
        if root_0_0 != 'GrpHdr':
            raise ValueError('expected GrpHdr, got: ' + root_0_0)

    def parse(self, cr, data):
        """Parse a camt.052, camt.053 or camt.054 file."""
        try:
            root = etree.fromstring(
                data, parser=etree.XMLParser(recover=True))
        except etree.XMLSyntaxError:
            # ABNAmro is known to mix up encodings
            root = etree.fromstring(
                data.decode('iso-8859-15').encode('utf-8'))
        if root is None:
            raise ValueError(
                'Not a valid xml file, or not an xml file at all.')
        ns = root.tag[1:root.tag.index("}")]
        self.check_version(ns, root)
        statements = []
        for node in root[0][1:]:
            statement = self.parse_statement(ns, node)
            if len(statement.transactions):
                statements.append(statement)
        return statements

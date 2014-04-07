# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction

__all__ = ['StockMove', 'Sale', 'SaleLine']
__metaclass__ = PoolMeta


class StockMove:
    __name__ = 'stock.move'

    from_openerp = fields.Boolean('Imported from OpenERP', readonly=True)
    from_openerp_to_invoice = fields.Boolean('Imported from OpenERP',
        readonly=True)

    @property
    def invoiced_quantity(self):
        if self.from_openerp:
            if self.from_openerp_to_invoice:
                return 0.0
            return self.quantity
        return super(StockMove, self).invoiced_quantity


class Sale:
    __name__ = 'sale.sale'

    from_openerp = fields.Boolean('Imported from OpenERP', readonly=True)

    def get_invoice_state(self):
        state = super(Sale, self).get_invoice_state()
        if not self.from_openerp or state == 'exception':
            return state
        if self.moves and any(m.from_openerp_to_invoice for m in self.moves):
            return 'waiting'
        elif self.moves and all(m.from_openerp for m in self.moves):
            # all moves invoiced
            if state == 'none':
                return 'paid'
        return state

    @classmethod
    def copy(cls, sales, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default['from_openerp'] = False
        return super(Sale, cls).copy(sales, default=default)


class SaleLine:
    __name__ = 'sale.line'

    def get_move(self, shipment_type):
        move = super(SaleLine, self).get_move(shipment_type)
        if move and self.sale.from_openerp:
            move.from_openerp = True
            if self.sale.invoice_method == 'shipment':
                move.from_openerp_to_invoice = True
        return move

    def get_invoice_line(self, invoice_type):
        pool = Pool()
        InvoiceLine = pool.get('account.invoice.line')
        Move = pool.get('stock.move')
        Uom = pool.get('product.uom')

        if (not self.sale.from_openerp or
                self.sale.invoice_method != 'shipment' or
                self.type != 'line' or
                not self.product or
                self.product.type == 'service'):
            return super(SaleLine, self).get_invoice_line(invoice_type)
        if not self.moves:
            return []

        with Transaction().set_user(0, set_context=True):
            invoice_line = InvoiceLine()
        invoice_line.type = self.type
        invoice_line.description = self.description
        invoice_line.note = self.note
        invoice_line.origin = self
        if (invoice_type == 'out_invoice') != (self.quantity >= 0):
            return []

        quantity = 0.0
        stock_moves = []
        for move in self.moves:
            if move.state == 'done' and move.from_openerp_to_invoice:
                quantity += Uom.compute_qty(move.uom, move.quantity,
                    self.unit)
                stock_moves.append(move)
        if quantity <= 0.0:
            return []
        invoice_line.stock_moves = stock_moves

        Move.write(stock_moves, {
                'from_openerp_to_invoice': False,
                })

        invoice_line.quantity = quantity
        invoice_line.unit = self.unit
        invoice_line.product = self.product
        invoice_line.unit_price = self.unit_price
        invoice_line.taxes = self.taxes
        invoice_line.invoice_type = invoice_type
        invoice_line.account = self.product.account_revenue_used
        if not invoice_line.account:
            self.raise_user_error('missing_account_revenue', {
                    'product': invoice_line.product.rec_name,
                    'sale': self.sale.rec_name,
                    })
        return [invoice_line]

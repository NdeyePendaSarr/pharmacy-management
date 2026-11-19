"""
Le franc CFA n'a pas de centimes : tout montant d'une vente est un nombre
entier de francs, et la caisse accepte le montant qu'elle affiche.
"""
from decimal import Decimal

from django.test import TestCase

from pharmanps_alou.testing import make_customer, make_medication
from sales import services


def is_whole(amount):
    return amount == amount.to_integral_value()


class FcfaRoundingTests(TestCase):
    def sell(self, medication, quantity=1, **data):
        return services.create_sale(None, {
            "items": [{"medication_id": medication.id, "quantity": quantity}],
            "payment_method": "carte",
            **data,
        })

    def test_discount_is_rounded_to_the_franc(self):
        # 333 − 5 % : 16,65 de remise → 17 ; total 316 (et non 316,35).
        sale = self.sell(make_medication(selling_price=Decimal("333")), discount_percentage="5")
        self.assertEqual(sale.discount_amount, Decimal("17"))
        self.assertEqual(sale.total, Decimal("316"))

    def test_half_franc_is_rounded_up(self):
        # 1 010 − 5 % : 50,5 de remise → 51 ; total 959.
        sale = self.sell(make_medication(selling_price=Decimal("1010")), discount_percentage="5")
        self.assertEqual(sale.discount_amount, Decimal("51"))
        self.assertEqual(sale.total, Decimal("959"))

    def test_cash_payment_of_the_displayed_total_is_accepted(self):
        medication = make_medication(selling_price=Decimal("333"))
        sale = self.sell(medication, payment_method="especes", discount_percentage="5", amount_paid=316)
        self.assertEqual(sale.total, Decimal("316"))
        self.assertEqual(sale.change_amount, Decimal("0"))

        sale = self.sell(medication, payment_method="especes", discount_percentage="5", amount_paid=1000)
        self.assertEqual(sale.change_amount, Decimal("684"))

    def test_amount_paid_with_decimals_is_rounded(self):
        sale = self.sell(
            make_medication(selling_price=Decimal("333")),
            payment_method="especes", discount_percentage="5", amount_paid="316.4",
        )
        self.assertEqual(sale.amount_paid, Decimal("316"))

    def test_line_subtotals_add_up_to_the_sale_subtotal(self):
        # Prix hérité avec des centimes (saisi avant la règle « prix entier ») :
        # chaque ligne est arrondie, et le sous-total est leur somme exacte.
        first = make_medication(selling_price=Decimal("333.33"))
        second = make_medication(selling_price=Decimal("100.50"))
        sale = services.create_sale(None, {
            "items": [
                {"medication_id": first.id, "quantity": 3},
                {"medication_id": second.id, "quantity": 1},
            ],
            "payment_method": "carte",
            "discount_percentage": "7.5",
        })
        items = list(sale.items.all())
        self.assertEqual(sorted(item.subtotal for item in items), [Decimal("101"), Decimal("1000")])
        self.assertEqual(sale.subtotal, sum(item.subtotal for item in items))
        for amount in (sale.subtotal, sale.discount_amount, sale.total, sale.amount_paid, sale.change_amount):
            self.assertTrue(is_whole(amount), amount)

    def test_credit_debt_is_a_whole_amount(self):
        customer = make_customer(credit_limit=Decimal("10000"))
        self.sell(
            make_medication(selling_price=Decimal("333")),
            payment_method="credit", customer_id=customer.id, discount_percentage="5", amount_paid=0,
        )
        customer.refresh_from_db()
        self.assertEqual(customer.current_credit, Decimal("316"))

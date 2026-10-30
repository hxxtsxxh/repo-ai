import unittest

from shop.api.serializers import serialize_money, serialize_payment
from shop.models.order import Order, OrderLine
from shop.models.payment import Payment
from shop.repository.users import UserRepository
from shop.services.notifications import Notifier
from shop.utils.money import format_money


class MoneyDisplayTest(unittest.TestCase):
    def setUp(self):
        self.notifier = Notifier(UserRepository())

    def test_refund_email(self):
        order = Order(id="ord_1", user_id="usr_1", lines=[OrderLine("TEE-0001", 1, 1999)])
        self.assertIn("-$5.00", self.notifier.refund_issued(order, 500).body)
        self.assertIn("-$0.01", self.notifier.refund_issued(order, 1).body)

    def test_currency_and_grouping_in_emails(self):
        order = Order(id="ord_2", user_id="usr_1", currency="EUR",
                      lines=[OrderLine("BAG-0001", 3, 45000)], total_cents=135000)
        body = self.notifier.order_placed(order).body
        self.assertIn("€450.00", body)
        self.assertIn("Total: €1,350.00", body)
        self.assertNotIn("$", body)
        payment = Payment(id="pay_1", order_id="ord_2", amount_cents=123456, currency="GBP")
        self.assertIn("£1,234.56", self.notifier.payment_received(order, payment).body)

    def test_api_display(self):
        self.assertEqual(serialize_money(100, "GBP")["display"], "£1.00")
        self.assertEqual(serialize_money(-500, "USD")["display"], "-$5.00")
        self.assertEqual(serialize_money(123456, "EUR")["display"], "€1,234.56")
        payment = Payment(id="pay_1", order_id="o", amount_cents=999, currency="GBP")
        self.assertEqual(serialize_payment(payment)["amount"]["display"], "£9.99")

    def test_regression_shared_helper(self):
        self.assertEqual(format_money(-500), "-$5.00")
        self.assertEqual(serialize_money(1999)["amount"], "19.99")


if __name__ == "__main__":
    unittest.main()

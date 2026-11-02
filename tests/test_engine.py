import random
import unittest
from netpay import (Obligation, build_plan, verify_plan, net_balances,
                    greedy_settle, exact_settle, components, estimate_fees)
from netpay.money import format_amount, format_currency_amount, to_units


def ob(i, d, c, amt, ccy="USD"):
    return Obligation(str(i), d, c, amt, ccy)


class TestEngine(unittest.TestCase):
    def test_circular_debt_cancels_fully(self):
        plan = build_plan([ob(1, "A", "B", 100), ob(2, "B", "C", 100), ob(3, "C", "A", 100)])
        self.assertEqual(plan.payments, [])
        self.assertEqual(plan.payments_saved, 3)

    def test_chain_collapses_to_one_payment(self):
        plan = build_plan([ob(1, "A", "B", 100), ob(2, "B", "C", 100)])
        self.assertEqual(len(plan.payments), 1)
        p = plan.payments[0]
        self.assertEqual((p.payer, p.payee, p.amount_units), ("A", "C", 100))

    def test_independent_groups_do_not_mix(self):
        obs = [ob(1, "A", "B", 50), ob(2, "X", "Y", 70)]
        self.assertEqual(len(components(obs)), 2)
        plan = build_plan(obs)
        self.assertEqual({(p.payer, p.payee) for p in plan.payments}, {("A", "B"), ("X", "Y")})

    def test_currencies_never_mixed(self):
        plan = build_plan([ob(1, "A", "B", 100, "USD"), ob(2, "B", "A", 100, "EUR")])
        self.assertEqual(len(plan.payments), 2)

    def test_exact_beats_greedy(self):
        bal = {'P0': 9, 'P1': -8, 'P2': 6, 'P3': -2, 'P4': 3, 'P5': 4, 'P6': -12}
        self.assertEqual(len(greedy_settle(bal)), 6)
        self.assertEqual(len(exact_settle(bal)), 5)

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            Obligation("1", "A", "A", 10)
        with self.assertRaises(ValueError):
            Obligation("1", "A", "B", 0)
        with self.assertRaises(TypeError):
            Obligation("1", "A", "B", 10.5)

    def test_four_decimal_unit_settlement(self):
        obligation = Obligation("1", "Alice", "Bob", to_units("12.3456"))
        plan = build_plan([obligation])
        self.assertEqual(plan.payments[0].amount_units, 123_456)
        self.assertEqual(format_amount(plan.payments[0].amount_units), "12.3456")
        with self.assertRaisesRegex(ValueError, "at most 4 decimal places"):
            to_units("12.34567")
        with self.assertRaisesRegex(ValueError, "at most 4 decimal places"):
            to_units("0.00001")

    def test_currency_codes_and_minor_unit_formatting(self):
        self.assertEqual(to_units("12.345", "KWD"), 123_450)
        self.assertEqual(format_currency_amount(123_450, "KWD"), "12.345")
        self.assertEqual(format_currency_amount(12_000_000, "JPY"), "1200")
        self.assertEqual(format_currency_amount(1_200_000, "USD"), "120.00")
        with self.assertRaisesRegex(ValueError, "unknown ISO 4217"):
            to_units("1", "ZZZ")

    def test_verify_catches_wrong_plan(self):
        obs = [ob(1, "A", "B", 100)]
        from netpay import Payment
        with self.assertRaises(AssertionError):
            verify_plan(obs, [Payment("A", "B", 99)])

    def test_fee_estimate(self):
        plan = build_plan([ob(1, "A", "B", 10_000)])
        self.assertEqual(estimate_fees(plan.payments, fixed_units=30, bps=100), 130)

    def test_random_property(self):
        rng = random.Random(42)
        for _ in range(300):
            parties = [f"P{i}" for i in range(rng.randint(2, 9))]
            obs = []
            for i in range(rng.randint(1, 25)):
                d, c = rng.sample(parties, 2)
                obs.append(ob(i, d, c, rng.randint(1, 50_000)))
            exact = build_plan(obs)                      # exact where small
            greedy = build_plan(obs, exact_limit=0)      # force greedy
            verify_plan(obs, exact.payments)
            verify_plan(obs, greedy.payments)
            self.assertLessEqual(exact.optimized_count, greedy.optimized_count)
            self.assertLessEqual(greedy.optimized_count, exact.naive_count)
            # money conservation: every party's net position is fully settled
            nb = net_balances(obs)
            for pay in exact.payments:
                nb[pay.payer] = nb.get(pay.payer, 0) + pay.amount_units
                nb[pay.payee] = nb.get(pay.payee, 0) - pay.amount_units
            self.assertTrue(all(v == 0 for v in nb.values()))


if __name__ == "__main__":
    unittest.main()

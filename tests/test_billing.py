import unittest
from datetime import datetime

from backend.billing import cents_to_money, money_to_cents, quote_cents
from backend.models import StorePricing


class BillingTests(unittest.TestCase):
    def setUp(self):
        self.pricing = StorePricing(
            workday_day_hourly_cents=600, workday_day_cap_cents=1800,
            workday_night_hourly_cents=1000, workday_night_cap_cents=3000,
            weekend_day_hourly_cents=800, weekend_day_cap_cents=2400,
            weekend_night_hourly_cents=1200, weekend_night_cap_cents=3600,
            holiday_day_hourly_cents=900, holiday_day_cap_cents=2700,
            holiday_night_hourly_cents=1400, holiday_night_cap_cents=4200,
        )

    def test_money_round_trip_uses_integer_cents(self):
        self.assertEqual(money_to_cents(12.34), 1234)
        self.assertEqual(cents_to_money(1234), 12.34)

    def test_daytime_hour_and_cap(self):
        _, one_hour = quote_cents(self.pricing, datetime(2026, 9, 7, 10), datetime(2026, 9, 7, 11))
        _, capped = quote_cents(self.pricing, datetime(2026, 9, 7, 8), datetime(2026, 9, 7, 17))
        self.assertEqual(one_hour, 600)
        self.assertEqual(capped, 1800)

    def test_cross_period_splits_at_18(self):
        minutes, due = quote_cents(self.pricing, datetime(2026, 9, 7, 17), datetime(2026, 9, 7, 19))
        self.assertEqual(minutes, 120)
        self.assertEqual(due, 1600)

    def test_holiday_override(self):
        _, due = quote_cents(self.pricing, datetime(2026, 9, 7, 10), datetime(2026, 9, 7, 12), "holiday")
        self.assertEqual(due, 1800)

    def test_rejects_reverse_time(self):
        with self.assertRaises(ValueError):
            quote_cents(self.pricing, datetime(2026, 9, 7, 12), datetime(2026, 9, 7, 11))


if __name__ == "__main__": unittest.main()

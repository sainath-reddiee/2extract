from __future__ import annotations

import unittest

from twextract.errors import TargetingError
from twextract.username import Targeting, build_username, slug


class UsernameTests(unittest.TestCase):
    BASE = "2xt-customer-a1b2-proxy-geo_scraper"

    def test_country_city(self) -> None:
        user = build_username(self.BASE, Targeting(country="DE", city="Berlin"))
        self.assertEqual(user, f"{self.BASE}-country-de-city-berlin")

    def test_state_required_country(self) -> None:
        with self.assertRaises(TargetingError):
            build_username(self.BASE, Targeting(city="berlin"))

    def test_geo_and_isp_conflict(self) -> None:
        with self.assertRaises(TargetingError):
            build_username(self.BASE, Targeting(country="us", isp="310260"))

    def test_mobile_isp(self) -> None:
        user = build_username(self.BASE, Targeting(isp="310260"))
        self.assertEqual(user, f"{self.BASE}-isp-310260")

    def test_zip(self) -> None:
        user = build_username(self.BASE, Targeting(country="us", zip_code="90210"))
        self.assertEqual(user, f"{self.BASE}-country-us-zip-90210")

    def test_const_is_flag(self) -> None:
        user = build_username(
            self.BASE,
            Targeting(country="us", session="abc123", time_minutes=30, const=True),
        )
        self.assertEqual(user, f"{self.BASE}-country-us-session-abc123-time-30-const")

    def test_time_needs_session(self) -> None:
        with self.assertRaises(TargetingError):
            build_username(self.BASE, Targeting(time_minutes=10))

    def test_session_rejects_hyphen(self) -> None:
        with self.assertRaises(TargetingError):
            build_username(self.BASE, Targeting(session="user-1"))

    def test_slug(self) -> None:
        self.assertEqual(slug("Los Angeles"), "losangeles")
        self.assertEqual(slug("New York"), "newyork")

    def test_real_residential_base_username(self) -> None:
        base = "2xt-customer-tQWbjCJPArY-proxy-sainath_test"
        user = build_username(base, Targeting(country="us"))
        self.assertEqual(user, f"{base}-country-us")


if __name__ == "__main__":
    unittest.main()

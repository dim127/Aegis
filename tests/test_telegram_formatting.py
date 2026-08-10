"""Telegram message formatting: readable on a phone, informative at a glance.

Not testing exact copy — that would make every wording tweak a broken test.
Testing the properties that matter: no raw floats without separators on
large numbers, no duplicated words from concatenating self-describing labels,
and the ordering/severity rules the messages depend on (R never quoted for an
unfilled signal, heartbeat counts match the lists).
"""
import unittest

import pandas as pd

import notifications.telegram_bot as t


def _setup(**over):
    base = {
        "direction": "long", "base": "BTC", "pair": "BTC/USDC:USDC",
        "tf_combo": "4h/15m", "entry": 63910.5, "sl": 63180.0, "tp": 65420.0,
        "rr": 2.07, "risk": 730.5, "risk_pct": 1.143,
        "poi_label": "4H FVG 63,120.00-64,050.00 (POI)",
        "sweep_price": 63240.0,
        "mss_label": "15M MSS CHOCH Bullish", "ote_label": "OTE 63,740.00-63,980.00",
        "tp_source": "swing",
        "timestamp": pd.Timestamp("2026-08-11 14:32", tz="UTC"),
    }
    base.update(over)
    return base


class FmtPriceTests(unittest.TestCase):
    def test_large_prices_get_thousands_separators(self):
        self.assertEqual(t.fmt_price(63910.5), "63,910.50")

    def test_sub_dollar_prices_stay_unseparated_but_precise(self):
        self.assertEqual(t.fmt_price(1.0612), "1.0612")

    def test_none_price_is_a_placeholder_not_a_crash(self):
        self.assertEqual(t.fmt_price(None), "?")

    def test_reference_drives_decimal_count_not_the_value_itself(self):
        # A TP under $1 must not get more decimals than its BTC-sized entry.
        self.assertEqual(t.fmt_price(0.5, reference=63910.5), "0.50")


class SetupMessageTests(unittest.TestCase):
    def test_no_duplicated_label_words_from_concatenation(self):
        # poi_label already says "POI"; mss_label already says "MSS". Prefixing
        # them again produces "POI ... (POI)" and "MSS ... MSS ...".
        msg = t.format_setup_message(_setup())
        self.assertNotIn("POI 4H", msg)
        self.assertNotIn("MSS 15M MSS", msg)

    def test_large_numbers_are_comma_formatted_in_the_price_block(self):
        msg = t.format_setup_message(_setup())
        self.assertIn("63,910.50", msg)

    def test_swing_target_is_tagged_distinctly_from_fallback(self):
        swing_msg = t.format_setup_message(_setup(tp_source="swing"))
        fallback_msg = t.format_setup_message(_setup(tp_source="multiple"))
        self.assertIn("swing", swing_msg)
        self.assertIn("fallback", fallback_msg)
        self.assertNotIn("fallback", swing_msg)

    def test_tp_tag_does_not_repeat_the_rr_number(self):
        # Regression: "(3.00R · 3R)" said the same number twice.
        msg = t.format_setup_message(_setup(tp_source="multiple", rr=3.0))
        self.assertNotIn("3R)", msg)

    def test_direction_and_pair_are_both_present(self):
        msg = t.format_setup_message(_setup(direction="short", base="XRP"))
        self.assertIn("XRP", msg)
        self.assertIn("SHORT", msg)


class HeartbeatTests(unittest.TestCase):
    def test_empty_report_says_nothing_active_rather_than_a_blank_message(self):
        msg = t.format_heartbeat({"valid": [], "invalid": []})
        self.assertIn("Tidak ada sinyal aktif", msg)

    def test_header_counts_match_the_lists(self):
        report = {
            "valid": [{"pair": "BTC/USDC:USDC", "tf_combo": "4h/15m",
                      "direction": "long", "status": "PENDING", "entry": 100.0,
                      "price": 99.0}],
            "invalid": [{"pair": "ETH/USDC:USDC", "tf_combo": "1h/5m",
                        "direction": "short", "reason": "SL sebelum entry"}],
        }
        msg = t.format_heartbeat(report)
        self.assertIn("1 aktif, 1 selesai", msg)

    def test_pending_signal_never_quotes_r(self):
        # R implies an open position; a PENDING signal has none yet.
        report = {"valid": [{"pair": "BTC/USDC:USDC", "tf_combo": "4h/15m",
                             "direction": "long", "status": "PENDING",
                             "entry": 100.0, "price": 99.0}], "invalid": []}
        msg = t.format_heartbeat(report)
        self.assertNotIn("R", msg.split("\n")[-1])

    def test_triggered_signal_reports_r(self):
        report = {"valid": [{"pair": "BTC/USDC:USDC", "tf_combo": "4h/15m",
                             "direction": "long", "status": "TRIGGERED",
                             "entry": 100.0, "price": 105.0, "progress_r": 1.0}],
                  "invalid": []}
        msg = t.format_heartbeat(report)
        self.assertIn("+1.00R", msg)

    def test_one_line_per_signal_no_matter_the_count(self):
        # The old format used two lines per valid signal plus section headers;
        # this must stay flat regardless of how many signals are live.
        valid = [{"pair": f"{p}/USDC:USDC", "tf_combo": "4h/15m", "direction": "long",
                  "status": "PENDING", "entry": 100.0, "price": 99.0}
                 for p in ("BTC", "ETH", "SOL")]
        msg = t.format_heartbeat({"valid": valid, "invalid": []})
        # header + 3 signal lines
        self.assertEqual(len(msg.strip().split("\n")), 4)


class OtherMessagesTests(unittest.TestCase):
    def test_no_trade_message_is_short(self):
        self.assertLess(len(t.format_no_trade_message()), 60)

    def test_scan_banner_reports_the_count(self):
        self.assertIn("5", t.format_scan_banner(5))

    def test_error_message_wraps_the_error_in_a_code_block(self):
        msg = t.format_error_message("boom")
        self.assertIn("boom", msg)
        self.assertIn("```", msg)


if __name__ == "__main__":
    unittest.main()

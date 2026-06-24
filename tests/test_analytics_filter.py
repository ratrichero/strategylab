import unittest

from app.services.analytics_filter import (
    AnalyticsFilter,
    build_sql_filter,
    normalize_symbols,
    parse_vn_date_range,
)


class AnalyticsFilterTests(unittest.TestCase):
    def test_vn_plain_date_range_to_utc_boundaries(self):
        start, end = parse_vn_date_range("2026-06-15", "2026-06-15")
        self.assertEqual(start.isoformat(), "2026-06-14T17:00:00")
        self.assertEqual(end.isoformat(), "2026-06-15T17:00:00")

    def test_normalize_symbols(self):
        self.assertEqual(normalize_symbols("btc, ETH SOLUSDT"), ["BTCUSDT", "ETHUSDT", "SOLUSDT"])

    def test_iso_datetime_with_timezone(self):
        start, end = parse_vn_date_range("2026-06-15T00:00:00+07:00", "2026-06-15T12:00:00+07:00")
        self.assertEqual(start.isoformat(), "2026-06-14T17:00:00")
        self.assertEqual(end.isoformat(), "2026-06-15T05:00:00")

    def test_default_closed_status_scope_is_win_loss(self):
        built = build_sql_filter(AnalyticsFilter(), source="closed")
        self.assertEqual(built.status_scope, "WIN_LOSS")
        self.assertIn(["WIN", "LOSS"], built.params)

    def test_include_manual_status_scope(self):
        built = build_sql_filter(AnalyticsFilter(include_manual=True), source="closed")
        self.assertEqual(built.status_scope, "WIN_LOSS_MANUAL")
        self.assertIn(["WIN", "LOSS", "MANUAL"], built.params)

    def test_open_source_uses_open_status_and_created_at_default(self):
        built = build_sql_filter(AnalyticsFilter(), source="open")
        self.assertEqual(built.status_scope, "OPEN")
        self.assertEqual(built.date_field, "created_at")
        self.assertIn(["OPEN"], built.params)

    def test_engine_newest_filter_is_parameterized(self):
        built = build_sql_filter(
            AnalyticsFilter(engine_version="3", engine_mode="newest"),
            source="closed",
        )
        self.assertIn("engine_version >= $2", built.where)
        self.assertEqual(built.params[1], 3.0)

    def test_engine_only_and_older_filters_are_parameterized(self):
        only = build_sql_filter(AnalyticsFilter(engine_version="3", engine_mode="only"), source="closed")
        older = build_sql_filter(AnalyticsFilter(engine_version="3", engine_mode="older"), source="closed")
        self.assertIn("engine_version = $2", only.where)
        self.assertIn("engine_version <= $2", older.where)
        self.assertEqual(only.params[1], 3.0)
        self.assertEqual(older.params[1], 3.0)

    def test_include_and_exclude_symbols_are_parameterized(self):
        include = build_sql_filter(AnalyticsFilter(symbols="btc eth", symbol_mode="include"), source="closed")
        exclude = build_sql_filter(AnalyticsFilter(symbols="btc eth", symbol_mode="exclude"), source="closed")
        self.assertIn("symbol = ANY", include.where)
        self.assertIn("symbol <> ALL", exclude.where)
        self.assertIn(["BTCUSDT", "ETHUSDT"], include.params)
        self.assertIn(["BTCUSDT", "ETHUSDT"], exclude.params)

    def test_empty_arrays_do_not_add_array_conditions(self):
        built = build_sql_filter(AnalyticsFilter(timeframes=[], strategies=[]), source="closed")
        self.assertNotIn("timeframe = ANY", built.where)
        self.assertNotIn("strategy_name = ANY", built.where)


if __name__ == "__main__":
    unittest.main()

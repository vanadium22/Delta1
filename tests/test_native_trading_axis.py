import unittest
from datetime import datetime
from dashboard.native.trading_axis import TradingTimeMap


def t(value): return datetime.fromisoformat(value+"+08:00").timestamp()


class TradingAxisTests(unittest.TestCase):
    def test_lunch_overnight_and_weekend_fold_without_changing_timestamps(self):
        times=[t(s) for s in ("2026-09-25T11:30:00","2026-09-25T13:01:00","2026-09-25T15:00:00","2026-09-28T09:31:00")]
        axis=TradingTimeMap(times,"1m")
        self.assertEqual(axis.coordinate(times[1])-axis.coordinate(times[0]),120)
        self.assertEqual(axis.coordinate(times[3])-axis.coordinate(times[2]),120)
        for stamp in times: self.assertEqual(axis.nearest_time(axis.coordinate(stamp)),stamp)
        self.assertEqual([name for _,name in axis.boundaries],["午休","09-28"])

    def test_in_session_gap_is_preserved_and_hover_does_not_invent_observation(self):
        stamps=[t("2026-09-30T10:00:00"),t("2026-09-30T10:10:00")]
        axis=TradingTimeMap(stamps)
        self.assertEqual(axis.coordinate(stamps[1])-axis.coordinate(stamps[0]),600)
        self.assertIsNone(axis.nearest_time(300))
        self.assertEqual(axis.label(300,True),"缺数")

    def test_off_session_filtered_and_all_curves_share_coordinates(self):
        stamps=[t("2026-09-30T09:15:00"),t("2026-09-30T10:00:00"),t("2026-09-30T10:01:00"),t("2026-09-30T12:00:00")]
        axis=TradingTimeMap(stamps)
        a=axis.project(stamps,[1,2,3,4]);b=axis.project(stamps[2:3],[99])
        self.assertEqual(a,([0.,60.],[2,3]));self.assertEqual(b,([60.],[99]))

    def test_daily_categories_fold_missing_calendar_dates(self):
        stamps=[t("2026-09-25T15:00:00"),t("2026-09-28T15:00:00")]
        axis=TradingTimeMap(stamps,"1d")
        self.assertEqual([axis.coordinate(s) for s in stamps],[0.,1.])
        self.assertEqual(axis.label(1),"2026-09-28")

    def test_seconds_and_missing_start_of_afternoon_keep_clock_spacing(self):
        stamps=[t("2026-09-30T11:30:00"),t("2026-09-30T13:10:00"),t("2026-09-30T13:10:01")]
        axis=TradingTimeMap(stamps,"1s")
        self.assertEqual(axis.coordinate(stamps[1]),601)
        self.assertEqual(axis.coordinate(stamps[2]),602)


if __name__=="__main__": unittest.main()

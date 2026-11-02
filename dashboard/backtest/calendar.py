"""Verified 2023/2024 SSE closures plus the existing 2025/2026 exchange calendar."""
from datetime import date, timedelta

from dashboard.marketdata.trading_calendar import CalendarUnavailable, HOLIDAYS

SOURCES = {
    2023: "https://www.sse.com.cn/disclosure/announcement/general/c/c_20221227_5714458.shtml",
    2024: "https://www.sse.com.cn/disclosure/announcement/general/c/c_20231226_5733939.shtml",
}
EARLIER = {
    2023: [("01-01", "01-02"), ("01-21", "01-27"), ("04-05", "04-05"), ("04-29", "05-03"),
           ("06-22", "06-24"), ("09-29", "10-06")],
    2024: [("01-01", "01-01"), ("02-09", "02-17"), ("04-04", "04-06"), ("05-01", "05-05"),
           ("06-10", "06-10"), ("09-15", "09-17"), ("10-01", "10-07")],
}


def verified_days(start, end):
    start, end = date.fromisoformat(str(start)[:10]), date.fromisoformat(str(end)[:10])
    closures = {**HOLIDAYS, **EARLIER}
    if any(year not in closures for year in range(start.year, end.year + 1)):
        raise CalendarUnavailable("Backtest calendar year requires an explicitly verified announcement")
    result, day = [], start
    while day <= end:
        ranges = closures[day.year]
        if day.weekday() < 5 and not any(a <= day.strftime("%m-%d") <= b for a, b in ranges):
            result.append(day.isoformat())
        day += timedelta(days=1)
    return result

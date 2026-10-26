"""Calendar dates for current observations and completed-session references."""
from datetime import date,datetime,timedelta,time
from zoneinfo import ZoneInfo


def latest_completed_session(now=None,*,ready_at=time(15,10)):
    from .trading_calendar import load_year,HOLIDAYS
    clock=now or datetime.now(ZoneInfo('Asia/Shanghai'))
    if clock.tzinfo is None:raise ValueError('交易日期判断需包含时区')
    local=clock.astimezone(ZoneInfo('Asia/Shanghai'))
    day=local.date() if local.time().replace(tzinfo=None)>=ready_at else local.date()-timedelta(days=1)
    for _ in range(40):
        if day.year not in HOLIDAYS:raise ValueError('交易日历尚未核验')
        if day.weekday()<5 and day.isoformat() not in load_year(day.year,'.'):
            return day.isoformat()
        day-=timedelta(days=1)
    raise ValueError('未找到已核验完成交易日')

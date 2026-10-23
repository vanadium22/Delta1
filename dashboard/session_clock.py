"""Local, offline market access policy. Never download a calendar to decide access."""
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo


def session_policy(now=None, calendar_cache=None):
    from dashboard.marketdata.trading_calendar import HOLIDAYS, load_year
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    if now.tzinfo is None:
        raise ValueError('Session clock requires an aware timestamp')
    local = now.astimezone(ZoneInfo('Asia/Shanghai'))
    day = local.date()
    known = day.year in HOLIDAYS
    if not known and calendar_cache:
        known = (Path(calendar_cache)/f'{day.year}.json').is_file() and (Path(calendar_cache)/f'{day.year}.html').is_file()
    if not known:
        allowed, reason = False, '交易日历未核验，仅使用本地数据'
    else:
        try:
            closed = load_year(day.year, calendar_cache or '.')
            trading = day.weekday() < 5 and str(day) not in closed
            allowed = trading and time(9, 29) <= local.time().replace(tzinfo=None) < time(15, 1)
            reason = '行情接入时段' if allowed else '休市日，仅使用本地数据' if not trading else '09:29前 / 15:01起，仅使用本地数据'
        except (ValueError, OSError, KeyError):
            allowed, reason = False, '交易日历校验失败，仅使用本地数据'
    return dict(allowed=allowed, reason=reason, checked_at=local.isoformat())


def realtime_prompt_policy(now=None,calendar_cache=None):
    """Only continuous trading sessions may show the manual-VPN reminder."""
    local=(now or datetime.now(ZoneInfo('Asia/Shanghai')))
    if local.tzinfo is None:raise ValueError('Session clock requires an aware timestamp')
    local=local.astimezone(ZoneInfo('Asia/Shanghai'))
    policy=session_policy(local,calendar_cache)
    clock=local.time().replace(tzinfo=None)
    session='am' if time(9,30)<=clock<time(11,30) else 'pm' if time(13)<=clock<time(15) else None
    return dict(allowed=bool(policy['allowed'] and session),reason=policy['reason'],
                key=f'{local.date()}:{session}' if session else None)


class SessionStop:
    """Recheck the clock after every collector wait, before reference/HTTP access."""
    def __init__(self, event, policy=session_policy):
        self.event, self.policy = event, policy

    def is_set(self):
        return self.event.is_set() or not self.policy()['allowed']

    def wait(self, seconds):
        return self.event.wait(seconds) or self.is_set()

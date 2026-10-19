"""Independent exchange calendar. Unknown years fail closed, never infer from bars."""
from datetime import date, timedelta
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
from .bars import _atomic_bytes, _json_bytes

SOURCES = {
    2025: 'https://www.sse.com.cn/disclosure/announcement/general/c/c_20241223_10767108.shtml',
    2026: 'https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml',
}
HOLIDAYS = {
    2025: [('01-01','01-01'),('01-28','02-04'),('04-04','04-06'),('05-01','05-05'),('05-31','06-02'),('10-01','10-08')],
    2026: [('01-01','01-03'),('02-15','02-23'),('04-04','04-06'),('05-01','05-05'),('06-19','06-21'),('09-25','09-27'),('10-01','10-07')],
}


class CalendarUnavailable(ValueError):
    pass


def parse_announcement(raw, year):
    text = html.unescape(re.sub('<[^>]+>', '', raw))
    text = re.sub(r'\s+', '', text)
    if f'{year}年部分节假日休市安排' not in text:
        raise CalendarUnavailable('Calendar announcement year mismatch')
    sections = re.findall(r'（[一二三四五六七八]）([^：]+)：([^。]+)', text)
    holidays = set();names = ''.join(s[0] for s in sections)
    if not all(s in names for s in ('元旦','春节','清明','劳动','端午','中秋','国庆')):
        raise CalendarUnavailable('Incomplete annual exchange announcement')
    for _, section in sections:
        closed = section.split('休市')[0]
        points = re.findall(r'(\d{1,2})月(\d{1,2})日', closed)
        if not 1 <= len(points) <= 2:
            raise CalendarUnavailable('Unknown calendar date format')
        start = date(year, *map(int, points[0]));end = date(year, *map(int, points[-1]))
        if not 0 <= (end-start).days <= 15:
            raise CalendarUnavailable('Invalid closure range')
        while start <= end:
            holidays.add(start.isoformat());start += timedelta(days=1)
    if not 15 <= len(holidays) <= 40:
        raise CalendarUnavailable('Unexpected annual calendar coverage')
    return sorted(holidays)


def load_year(year, cache):
    if year in HOLIDAYS:
        days = set()
        for a,b in HOLIDAYS[year]:
            start,end = date.fromisoformat(f'{year}-{a}'),date.fromisoformat(f'{year}-{b}')
            while start <= end:days.add(start.isoformat());start += timedelta(days=1)
        return days
    path = Path(cache)/f'{year}.json'
    if path.exists():
        value=json.loads(path.read_text(encoding='utf8'))
        raw=path.with_suffix('.html').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=value['sha256']:
            raise CalendarUnavailable('Calendar evidence checksum mismatch')
        return set(parse_announcement(raw.decode('utf8'),year))
    # Future years refresh only from the official HTTPS list. No weekday fallback.
    try:
        import requests
        with requests.Session() as session:
            response=session.get('https://www.sse.com.cn/disclosure/dealinstruc/closed/list/',timeout=(3,8));response.raise_for_status()
            response.encoding='utf8'
            links=re.findall(r'<a\b[^>]*href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>',response.text,re.S)
            matches=[urljoin(response.url,link) for link,title in links
                     if f'{year}年部分节假日休市安排' in re.sub('<[^>]+>','',title)]
            if not matches:raise CalendarUnavailable('Annual calendar not yet available')
            url=matches[0]
            if urlsplit(url).scheme!='https' or urlsplit(url).hostname!='www.sse.com.cn':
                raise CalendarUnavailable('Unexpected calendar origin')
            response=session.get(url,timeout=(3,8));response.raise_for_status();raw=response.content
            days=parse_announcement(raw.decode('utf8'),year)
            _atomic_bytes(path.with_suffix('.html'),raw)
            _atomic_bytes(path,_json_bytes(dict(year=year,source=url,sha256=hashlib.sha256(raw).hexdigest())))
            return set(days)
    except CalendarUnavailable:raise
    except Exception:raise CalendarUnavailable('Official calendar unavailable; waiting') from None


def trading_days(start, today, cache):
    start,today = date.fromisoformat(str(start)),date.fromisoformat(str(today))
    # Include the previous year for a Jan 1 cutoff, but do not query unused years.
    begin = min(start, today-timedelta(days=20))
    closed = {y:load_year(y,cache) for y in range(begin.year,today.year+1)}
    days=[];day=begin
    while day < today:  # Always excludes today, even after the market close.
        if day.weekday()<5 and day.isoformat() not in closed[day.year]:days.append(day.isoformat())
        day+=timedelta(days=1)
    if not days:raise CalendarUnavailable('No verified previous trading day')
    return [d for d in days if d>=str(start)],days[-1]

"""One compact data-time status. Repainting never advances the data clock."""
import pandas as pd


def at(value):
    try:
        value = pd.Timestamp(value)
        return value if not pd.isna(value) and value.tzinfo is not None else None
    except (ValueError,TypeError):
        return None


def status(data, pipeline=None, *, now=None):
    now=pd.Timestamp(now or pd.Timestamp.now(tz='UTC'))
    rows = [*data.get('indices', []),*data.get('futures', [])]
    good = [r for r in rows if r.get('price') is not None and at(r.get('source_at')) is not None]
    source = min((at(r['source_at']) for r in good),default=None)
    if not good:
        label = '等待行情'
    elif len(good)==20 and all(r.get('quality',{}).get('usable') and at(r.get('received_at')) is not None
            and 0 <= (now-at(r['received_at'])).total_seconds() <= 30
            and -3 <= (now-at(r['source_at'])).total_seconds() <= 30 for r in good):
        label = '实时 · '+source.tz_convert('Asia/Shanghai').strftime('%H:%M:%S')
    else:
        kinds = {r.get('display_kind') for r in good}
        title = '收盘参考' if kinds=={'completed_daily'} else '缓存参考' if not data.get('market_session',{}).get('continuous') else '部分缓存'
        label = title+' · '+source.tz_convert('Asia/Shanghai').strftime('%m-%d %H:%M:%S')
    if pipeline is not None:
        history = getattr(pipeline,'history',None)
        wind = getattr(pipeline,'overview_reference',None)
        dividends = getattr(pipeline,'overview_dividends',None)
        if history is not None and history.process is not None:
            label += ' · DDB更新中'
        elif wind is not None and wind.running():
            label += ' · Wind更新中'
        elif dividends is not None and dividends.running():
            label += ' · 分红更新中'
    detail = '\n'.join(str(r.get('symbol',''))+'  源 '+str(r.get('source_at') or '—')+'  接收 '+str(r.get('received_at') or '—') for r in rows)
    return label, detail

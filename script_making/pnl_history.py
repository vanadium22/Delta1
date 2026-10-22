"""Independent OTC/group history snapshots and self-addressed mail artifacts."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses
import hashlib
from html import escape
import json
import os
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile
from xml.etree.ElementTree import ParseError

from .statistics import pnl_statistics
from .pnl_sectors import amount
from .storage import ReportError, atomic_json, sha256, timestamp, today

CONFIG_NAME = 'pnl_history.local.json'
VERSION = 1
IMAGES = (('otc_pnl.png', 'otc-pnl@self-report', '场外业务合计 · 收益历史'),
          ('groups_pnl.png', 'groups-pnl@self-report', '各组 · 收益历史'))
REQUIRED = {item[0] for item in IMAGES} | {'邮件草稿.eml', '邮件正文.txt', '统计记录.json', '邮件设置.json'}


def self_config(values):
    if not isinstance(values, dict) or set(values) != {'to'} or not isinstance(values['to'], str):
        raise ReportError('独立收益任务仅接受一个本人收件地址，不接受抄送或密送配置。')
    text = values['to'].strip()
    addresses = getaddresses([text])
    if (any(c in text for c in '\r\n;,') or len(addresses) != 1
            or addresses[0][0] or addresses[0][1] != text or text.count('@') != 1
            or not all(text.split('@')) or any(c.isspace() for c in text)):
        raise ReportError('请只填写一个完整的本人邮箱地址，不填写姓名、多人地址、抄送或密送。')
    return {'to': text}


def load_self_config(root):
    path = Path(root) / CONFIG_NAME
    if not path.is_file():
        raise ReportError('尚未配置独立任务的本人邮箱，请先运行 --set-self-email <本人邮箱>。')
    return self_config(json.loads(path.read_text(encoding='utf-8')))


def build_history(service, through, config):
    year = today().year
    snapshot = {'id': uuid4().hex, 'created_at': timestamp(), 'kind': 'otc_group_history',
                'config': self_config(config), 'year': year, 'through': through,
                'sources': {}, 'reports': [], 'errors': {}, 'otc': [], 'groups': []}
    entries = sorted((entry for entry in service.query_catalog()['dates']
                      if 'pnl' in entry['files'] and f'{year}-01-01' <= entry['date'] <= through),
                     key=lambda e: e['date'])
    if not entries:
        raise ReportError('截至本次来源日期，没有当年的盈亏统计报表。')
    if entries[-1]['date'] != through:
        raise ReportError('本次来源日期未在本地归档中取得，未退回旧日期。')
    cache = service.settings.data_path() / 'statistics/pnl_group_history_cache'
    names = []
    for entry in entries:
        day = entry['date']
        report = {'date': day, 'otc': None, 'groups': [], 'notes': []}
        snapshot['reports'].append(report)
        try:
            path = Path(entry['files']['pnl']['path'])
            digest = sha256(path)
            snapshot['sources'][day] = {'date': day, 'path': str(path), 'sha256': digest}
            key = hashlib.sha256(f'otc-groups-{VERSION}|{day}|{digest}'.encode()).hexdigest()
            cached = cache / (key + '.json')
            data = None
            if cached.is_file():
                try:
                    data = json.loads(cached.read_text(encoding='utf-8'))
                    amount(data['otc']['value'], '场外业务合计缓存')
                    for g in data['groups']:
                        amount(g['value'], g['name'] + '历史缓存')
                    if not data['groups'] or len({g['name'] for g in data['groups']}) != len(data['groups']):
                        raise ValueError('缓存组结构无效')
                    if abs(sum((amount(g['value'], '组缓存') for g in data['groups']), Decimal(0))
                           - amount(data['otc']['value'], '合计缓存')) > Decimal('0.01'):
                        raise ValueError('缓存合计不一致')
                except (ValueError, KeyError, TypeError):
                    data = None
            if data is None:
                pnl = pnl_statistics(path, day)
                view = pnl['presentation']
                if view['diagnostics']:
                    raise ReportError('无法可靠识别互不重复分组：' + '；'.join(view['diagnostics']))
                if not view['otc'] or not view['groups']:
                    raise ReportError('场外业务合计或组汇总缺失。')
                amount(view['otc']['value'], '场外业务合计')
                data = {'otc': view['otc'], 'groups': view['groups'], 'notes': pnl['notes']}
                if sha256(path) != digest:
                    raise ReportError('读取期间盈亏统计发生变化，请重新生成。')
                atomic_json(cached, data)
            report.update(deepcopy(data))
            for group in data['groups']:
                if group['name'] not in names:
                    names.append(group['name'])
        except (OSError, ValueError, KeyError, TypeError, BadZipFile, ParseError) as exc:
            snapshot['errors'][day] = str(exc)
    # Each group's gap resets only that group's difference. Missing groups are not zero.
    def series(name=None):
        result, previous = [], None
        for report in snapshot['reports']:
            raw = report['otc'] if name is None else next((g for g in report['groups'] if g['name'] == name), None)
            point = {'date': report['date'], 'current': None, 'change': None,
                     'previous_date': None, 'source_rows': []}
            if raw:
                point.update(current=str(amount(raw['value'], '历史净利润')),
                             source_rows=raw.get('source_rows', [raw['row']]))
                if previous:
                    point.update(change=str(Decimal(point['current']) - Decimal(previous['current'])),
                                 previous_date=previous['date'])
                previous = point
            else:
                previous = None
            result.append(point)
        return result
    snapshot['otc'] = series()
    latest_names = [g['name'] for g in snapshot['reports'][-1]['groups']]
    names = latest_names + [name for name in names if name not in latest_names]
    snapshot['groups'] = [{'name': name, 'points': series(name)} for name in names]
    for source in snapshot['sources'].values():
        if sha256(Path(source['path'])) != source['sha256']:
            raise ReportError('计算期间来源发生变化，请重新生成。')
    return snapshot


def render_history(snapshot):
    from .statistics_charts import chart_html
    from .statistics_export import document, metric_cards
    def panel(points, title):
        latest = points[-1]
        history = {'year': snapshot['year'], 'through': snapshot['through'], 'points': points, 'errors': snapshot['errors']}
        body = metric_cards(latest)
        body += chart_html({'history': {'pnl': history}}, title=title,
                           precise_ticks=True,
                           timing_note='横轴为报表日期；各组收益归属以原表注释为准。柱形为相邻报表区间差额。',
                           source='来源：盈亏统计 / 累积盈亏统计 / 净利润；原行号见本图说明及统计记录',
                           period_note='相邻报表的区间变动；缺值断线，首份或前份缺失时不相减。')
        return body + '<p class="note">本期原Excel行号：' + escape(' + '.join(map(str, latest['source_rows'])) or '本期未取得') + '</p>'
    intro = (f"<p>来源报表：{escape(snapshot['through'])} · {snapshot['year']}年年初至所选日期 · 金额图示单位：万元</p>"
             '<p class="note">只读Excel保存的累计净利润缓存。各组收益归属以原表注释为准，保留缺日区间口径，跨年重新开始。</p>')
    notes = snapshot['reports'][-1].get('notes', [])
    if notes:
        intro += '<p class="note">原表注释：' + escape('；'.join(notes)) + '</p>'
    otc = document('场外业务合计 · 收益历史', intro + panel(snapshot['otc'], '场外业务合计 · 累计净利润与两期变动'), snapshot)
    body = intro + '<p>消费 = 消费 + 周期-消费代管；周期 = 周期 + 周期-其他；原境内个股期权台不再重复计入。各组按原表顺序排列，非收益排名。</p>'
    for group in snapshot['groups']:
        body += '<h2>' + escape(group['name']) + '</h2>' + panel(group['points'], '组收益 · 累计净利润与两期变动')
    return otc, document('各组 · 收益历史', body, snapshot)


def export_history(base, snapshot):
    from .statistics_export import save_image
    if snapshot['errors'] or not snapshot['otc'] or snapshot['otc'][-1]['change'] is None:
        raise ReportError('收益历史或上期数值不完整，不能生成可发送草稿。')
    config = self_config(snapshot['config'])
    folder = Path(base) / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + snapshot['id'][:10])
    folder.mkdir(parents=True, exist_ok=False)
    try:
        for page, (name, _, _) in zip(render_history(snapshot), IMAGES):
            save_image(page, folder / name)
        subject = f"场外业务与各组收益历史 {snapshot['through']}"
        body = (f"本人查阅：{snapshot['through']}场外业务合计及各组累计净利润历史。\n"
                '两图见正文及附件；消费、周期按已确认规则合并。\n各组收益归属以原表注释为准（含T-2说明）；相邻报表差额可能为缺日区间变动。')
        html = '<html><body><p>' + escape(body).replace('\n', '<br>') + '</p>'
        html += ''.join(f'<h2>{title}</h2><img src="cid:{cid}" alt="{title}" width="1100">' for _, cid, title in IMAGES)
        html += '</body></html>'
        alternative = EmailMessage(policy=policy.SMTP)
        alternative.set_content(body)
        alternative.add_alternative(html, subtype='html')
        message = EmailMessage(policy=policy.SMTP)
        message['To'], message['Subject'], message['X-Unsent'] = config['to'], subject, '1'
        message.make_related()
        message['MIME-Version'] = '1.0'
        message.set_param('type', 'multipart/alternative')
        message.attach(alternative)
        for name, cid, _ in IMAGES:
            message.add_related((folder / name).read_bytes(), maintype='image', subtype='png',
                                filename=name, cid=f'<{cid}>', disposition='inline')
        (folder / '邮件草稿.eml').write_bytes(message.as_bytes())
        (folder / '邮件正文.txt').write_text(subject + '\n\n' + body, encoding='utf-8')
        atomic_json(folder / '统计记录.json', snapshot)
        atomic_json(folder / '邮件设置.json', config)
    except Exception:
        (folder / '导出未完成.txt').write_text('本次导出未完成，请勿使用此目录的部分结果。', encoding='utf-8')
        raise
    return folder


def mail_manifest(folder):
    folder = Path(folder).resolve(strict=True)
    if (folder / '导出未完成.txt').exists() or not all((folder / name).is_file() for name in REQUIRED):
        raise ReportError('独立收益产物不完整。')
    message = BytesParser(policy=policy.default).parsebytes((folder / '邮件草稿.eml').read_bytes())
    config = self_config(json.loads((folder / '邮件设置.json').read_text(encoding='utf-8')))
    if message.get_all('Cc') or message.get_all('Bcc') or getaddresses(message.get_all('To', [])) != [('', config['to'])]:
        raise ReportError('独立任务草稿收件人不符合仅发给本人设置。')
    plain, html = message.get_body(('plain',)), message.get_body(('html',))
    if message.defects or plain is None or html is None:
        raise ReportError('独立任务草稿正文无效。')
    parts = [p for p in message.walk() if p.get_filename()]
    if len(parts) != 2 or {p.get_filename() for p in parts} != {item[0] for item in IMAGES}:
        raise ReportError('独立任务必须且仅包含本次两张收益图片。')
    attachments = []
    for name, cid, _ in IMAGES:
        part = next(p for p in parts if p.get_filename() == name)
        path = (folder / name).resolve(strict=True)
        if path.parent != folder or part.get_payload(decode=True) != path.read_bytes() or str(part.get('Content-ID')) != f'<{cid}>':
            raise ReportError('独立收益图片与草稿不一致。')
        attachments.append({'path': str(path), 'size': path.stat().st_size, 'sha256': sha256(path),
                            'content_id': cid, 'content_type': 'image/png'})
    return {'delivery_key': hashlib.sha256(('pnl-history|' + os.path.normcase(str(folder))).encode()).hexdigest(),
            'mail': {'to': [config['to']], 'cc': [], 'bcc': [], 'subject': str(message['Subject']),
                     'body': plain.get_content(), 'html_body': html.get_content(), 'attachments': attachments}}

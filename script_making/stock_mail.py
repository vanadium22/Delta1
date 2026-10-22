"""Independent filtered stock-exposure mail; no SMTP or scheduling side effects."""
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses
import hashlib
from html import escape
import json
import os
from pathlib import Path

from .statistics_export import money, save_image, stocks_page
from .storage import ReportError, atomic_json, sha256

CONFIG = 'stock_mail.local.json'
VERSION = 2
IMAGE_CID = 'swap-stocks@stock-report'
DEFAULT = {'to': '', 'cc': '', 'subject': '收益互换纯个股敞口 {{date}}', 'note': ''}
REQUIRED = {'swap_stocks.png', '邮件草稿.eml', '邮件正文.txt', '邮件设置.json', '统计记录.json'}


def addresses(raw):
    if not isinstance(raw, str) or any(c in raw for c in '\r\n'):
        raise ReportError('邮箱地址必须为单行文本。')
    raw = raw.replace('，', ',').replace('；', ',').replace(';', ',').strip()
    if not raw:
        return []
    parsed = getaddresses([raw])
    if not parsed or any(not addr or addr.count('@') != 1 or not all(addr.split('@'))
                         or any(c.isspace() for c in addr) for _, addr in parsed):
        raise ReportError('请输入完整邮箱地址，多个地址用逗号分隔。')
    return list(dict.fromkeys(addr for _, addr in parsed))


def profile(values, *, require_to=False):
    if not isinstance(values, dict) or set(values) - set(DEFAULT):
        raise ReportError('纯个股任务邮件设置字段无效。')
    result = {**DEFAULT, **values}
    if any(not isinstance(v, str) for v in result.values()):
        raise ReportError('纯个股任务邮件设置必须为文本。')
    for field in ('to', 'cc'):
        result[field] = ', '.join(addresses(result[field]))
    if require_to and not result['to']:
        raise ReportError('请先在日报「统计 → 独立任务邮箱」配置纯个股任务收件人。')
    if not result['subject'].strip() or any(c in result['subject'] for c in '\r\n'):
        raise ReportError('邮件主题不能为空或包含换行。')
    return result


def load_profile(root, *, require_to=False):
    path = Path(root) / CONFIG
    return profile(json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}, require_to=require_to)


def content(snapshot, values):
    group, filters = snapshot['swap_stocks'], snapshot['config']
    subject = values['subject'].replace('{{date}}', group['date'])
    body = (f"收益互换日报 {group['date']}｜筛选后纯个股敞口\n\n"
            f"来源：收益互换日报 / 风险盈亏统计。仅含股票，不含指数、股指期货及任何ETF。\n"
            f"筛选条件：|{filters['metric']}| ≥ {money(filters['threshold'])}；沿用日报阈值和永久剔除名单。\n"
            f"本次入选 {group['count']} 项；带符号Delta总敞口金额合计 {money(group['net'])} 元。\n"
            f"总盈亏合计 {money(group['total'])} 元；当日盈亏合计 {money(group['daily'])} 元。\n\n"
            '敞口金额按原表正负号相加；不同标的的Delta数量不相加，图片合计数量列为“—”。'
            '这是筛选后的纯个股子集，不是未筛选的全台敞口，合计不必等于包含其他ETF的原组。\n'
            '金额单位为元；Delta数量沿用原表单位。明细及高亮合计见正文图片及附件 swap_stocks.png。')
    if not group['count']:
        body += '\n本次没有达到筛选条件的股票，金额合计为零；来源已成功读取。'
    if values['note'].strip():
        body += '\n\n' + values['note'].strip()
    return subject, body


def export(base, snapshot, values):
    values = profile(values, require_to=True)
    if snapshot.get('errors') or snapshot.get('swap_stocks') is None:
        raise ReportError('纯个股统计不完整，不能生成可发送草稿。')
    folder = Path(base) / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + snapshot['id'][:10])
    folder.mkdir(parents=True, exist_ok=False)
    try:
        save_image(stocks_page(snapshot), folder / 'swap_stocks.png')
        subject, body = content(snapshot, values)
        message = EmailMessage(policy=policy.SMTP)
        message['To'], message['Subject'], message['X-Unsent'] = values['to'], subject, '1'
        if values['cc']:
            message['Cc'] = values['cc']
        alternatives = EmailMessage(policy=policy.SMTP)
        alternatives.set_content(body)
        html = ('<html><body><p>' + escape(body).replace('\n', '<br>') + '</p>'
                '<h2>收益互换 · 纯个股敞口</h2>'
                f'<img src="cid:{IMAGE_CID}" alt="收益互换纯个股敞口明细" width="1100" '
                'style="display:block;width:100%;max-width:1600px;height:auto"></body></html>')
        alternatives.add_alternative(html, subtype='html')
        message.make_related()
        message['MIME-Version'] = '1.0'
        message.set_param('type', 'multipart/alternative')
        message.attach(alternatives)
        message.add_related((folder / 'swap_stocks.png').read_bytes(), maintype='image', subtype='png',
                            filename='swap_stocks.png', cid=f'<{IMAGE_CID}>', disposition='inline')
        message.add_attachment((folder / 'swap_stocks.png').read_bytes(), maintype='image', subtype='png',
                               filename='swap_stocks.png')
        (folder / '邮件草稿.eml').write_bytes(message.as_bytes())
        (folder / '邮件正文.txt').write_text(subject + '\n\n' + body, encoding='utf-8')
        atomic_json(folder / '邮件设置.json', values)
        atomic_json(folder / '统计记录.json', snapshot)
    except Exception:
        (folder / '导出未完成.txt').write_text('本次导出未完成，请勿使用部分结果。', encoding='utf-8')
        raise
    return folder


def mail_manifest(folder):
    folder = Path(folder).resolve(strict=True)
    if (folder / '导出未完成.txt').exists() or not all((folder / name).is_file() for name in REQUIRED):
        raise ReportError('纯个股任务产物不完整。')
    values = profile(json.loads((folder / '邮件设置.json').read_text(encoding='utf-8')), require_to=True)
    message = BytesParser(policy=policy.default).parsebytes((folder / '邮件草稿.eml').read_bytes())
    if (message.defects or message.get_all('Bcc')
            or any([addr for _, addr in getaddresses(message.get_all(field, []))] != addresses(values[field]) for field in ('to', 'cc'))):
        raise ReportError('纯个股草稿地址与独立设置不一致。')
    plain, html = message.get_body(('plain',)), message.get_body(('html',))
    parts = [part for part in message.walk() if part.get_filename()]
    image = folder / 'swap_stocks.png'
    if (plain is None or html is None or len(parts) != 2
            or any(part.get_filename() != image.name or part.get_content_type() != 'image/png'
                   or part.get_payload(decode=True) != image.read_bytes() for part in parts)
            or parts[0].get_content_disposition() != 'inline'
            or str(parts[0].get('Content-ID')) != f'<{IMAGE_CID}>'
            or parts[1].get_content_disposition() != 'attachment' or parts[1].get('Content-ID') is not None
            or f'src="cid:{IMAGE_CID}"' not in html.get_content()
            or message.get_content_type() != 'multipart/mixed'):
        raise ReportError('纯个股草稿正文或附件无效。')
    return {'delivery_key': hashlib.sha256(('swap-stocks|' + os.path.normcase(str(folder))).encode()).hexdigest(),
            'mail': {'to': addresses(values['to']), 'cc': addresses(values['cc']), 'bcc': [],
                     'subject': str(message['Subject']), 'body': plain.get_content(), 'html_body': html.get_content(),
                     'attachments': [{'path': str(image), 'size': image.stat().st_size,
                                      'sha256': sha256(image), 'content_id': IMAGE_CID,
                                      'content_type': 'image/png', 'also_attach': True}]}}

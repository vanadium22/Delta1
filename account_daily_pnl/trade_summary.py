"""Fetch and summarize the Shanghai business date's BCT trades for Work Automation."""

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
from email.errors import HeaderParseError
from email.headerregistry import Address
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from openpyxl.styles import Alignment, Font, PatternFill

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from index_futures_basis.recent_brief.work_automation import find_work_automation
from shared_data.io import atomic_json, file_lock, sha256
from shared_data.paths import DataPaths

from account_daily_pnl.baseline import ACCOUNTS, ACCOUNT_IDS
from account_daily_pnl.ledger import ZERO, money
from account_daily_pnl.setup_daily import configure_credentials, register_task
from account_daily_pnl.sources import archive_batch, read_source, write_book


REPO = Path(__file__).resolve().parents[1]
TASK_NAME = "三账户当日成交汇总"
CLOCK = "15:30"
MAIL_CONFIG = "trade_summary_mail.local.json"
ALL_ACCOUNTS = "三账户合计"
DIRECTIONS = {"BUYER": ("买入", 1), "SELLER": ("卖出", -1)}
COLUMNS = ("交易日", "标的", "买卖方向", "变动数量", "币种", "累计成交金额", "成交笔数")
BAND_FILLS = tuple(PatternFill("solid", fgColor=color) for color in ("FFEAF2FB", "FFFFFFFF"))
DIRECTION_STYLES = {
    "买入": (PatternFill("solid", fgColor="FFFBE6E8"), Font(bold=True, color="FFA6293B")),
    "卖出": (PatternFill("solid", fgColor="FFE0F0E6"), Font(bold=True, color="FF176648")),
}
CENTER = Alignment(horizontal="center", vertical="center")
MIDDLE = Alignment(vertical="center")


def validate_recipients(addresses):
    unique = {}
    for address in addresses:
        if not isinstance(address, str) or not re.fullmatch(r"[^\s,@;<>]+@[^\s,@;<>]+", address):
            raise ValueError("请填写完整邮箱地址，多个邮箱用逗号或换行分开。")
        try:
            parsed = Address(addr_spec=address)
        except (ValueError, HeaderParseError) as exc:
            raise ValueError("收件邮箱地址格式有误。") from exc
        unique.setdefault((parsed.username, parsed.domain.lower()), address)
    if not unique:
        raise ValueError("请先设置当日成交汇总的收件人。")
    return list(unique.values())


def recipients_from_text(value):
    return validate_recipients(re.split(r"[\s,;，；]+", value.strip()))


def read_recipients(path):
    if not path.is_file():
        return []
    values = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(values, dict) or not isinstance(values.get("to"), list):
        raise ValueError("当日成交汇总的收件人设置无效。")
    return validate_recipients(values["to"])


def edit_recipients(previous):
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

    app = QApplication.instance() or QApplication([])
    dialog = QInputDialog(app.activeWindow())
    dialog.setOption(QInputDialog.InputDialogOption.UsePlainTextEditForTextInput)
    dialog.setWindowTitle(TASK_NAME + " · 邮件收件人")
    dialog.setLabelText("每行一个邮箱，也可以用逗号分隔。")
    dialog.setOkButtonText("保存")
    dialog.setCancelButtonText("取消")
    dialog.setFont(QFont("Microsoft YaHei UI", 10))
    dialog.setMinimumWidth(440)
    dialog.setTextValue("\n".join(previous))
    while dialog.exec():
        try:
            return recipients_from_text(dialog.textValue())
        except ValueError as exc:
            QMessageBox.warning(dialog, TASK_NAME, str(exc))
    return None


def task_definition(data, outputs, config, bct_script):
    program = Path(__file__).resolve()
    arguments = ["--scheduled", "--data", str(data), "--output", str(outputs)]
    for flag, path in (("--config", config), ("--bct-script", bct_script)):
        if path is not None:
            arguments.extend((flag, str(path.resolve())))
    return {
        "id": "account-trades-" + uuid5(NAMESPACE_URL, os.path.normcase(str(program))).hex,
        "name": TASK_NAME, "program": str(program), "cwd": str(REPO), "interpreter": sys.executable,
        "arguments": arguments, "enabled": True, "schedule": {"type": "daily", "time": CLOCK},
        "auto_catch_up": False, "result_mail": "queue",
    }


def report_tables(day, rows):
    summaries = {name: defaultdict(lambda: [ZERO, ZERO, 0]) for name in (ALL_ACCOUNTS, *ACCOUNTS)}
    stats = Counter()
    for index, row in enumerate(rows, 2):
        if row["type"] != "TRADE":
            stats["non_trade"] += 1
            continue
        source_account = row["tradeAccount"]
        account = ACCOUNT_IDS.get(source_account)
        if account is None:
            stats["other_account" if source_account else "unassigned"] += 1
            continue
        code = str(row["instrumentId"] or "").strip().upper()
        currency = str(row["currencyCode"] or "").strip().upper()
        side = row["direction"]
        try:
            if not code or not re.fullmatch(r"[A-Z]{3}", currency) or side not in DIRECTIONS:
                raise ValueError("标的、币种或买卖方向无效。")
            quantity, gross = money(row["dealAmount"]), money(row["dealBalance"])
            if quantity <= 0 or gross < 0:
                raise ValueError("成交数量须为正，金额须为非负。")
        except ValueError as exc:
            raise ValueError(f"{day} 账户 {account} 原始流水第 {index} 行：{exc}") from exc

        key = code, side, currency
        sign = DIRECTIONS[side][1]
        for name in (ALL_ACCOUNTS, account):
            sums = summaries[name][key]
            sums[0] += quantity * sign
            sums[1] += gross * sign
            sums[2] += 1
        stats["trades"] += 1

    tables = [
        (name, COLUMNS, [(day, code, DIRECTIONS[side][0], qty, currency, gross, count)
                         for (code, side, currency), (qty, gross, count) in sorted(groups.items())])
        for name, groups in summaries.items()
    ]
    tables.append(("取数说明", ("项目", "说明"), [
        ("交易日", day.isoformat()),
        ("数据来源", "BCT 境内权益互换台当日流水"),
        ("范围", "2602（BCT 5102）、5526、5524 的成交记录"),
        ("变动数量", "按流水单位，买入为正、卖出为负，期货为手"),
        ("累计成交金额", "当日同标的、同方向、同币种的费前成交金额合计，买入为正、卖出为负"),
        ("BCT 原始记录数", len(rows)),
        ("已纳入成交笔数", stats["trades"]),
        ("排除的非成交记录", stats["non_trade"]),
        ("其他账户成交笔数", stats["other_account"]),
        ("交易账户缺失笔数", stats["unassigned"]),
        ("结果", "已统计当日成交" if stats["trades"] else "三账户当日无可归属成交"),
    ]))
    return tables, stats


def content_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def style_trade_row(band_by_instrument, row, cells):
    band = band_by_instrument[row[1]]
    for cell in cells:
        cell.fill = band
        cell.alignment = MIDDLE
    indicator_fill, indicator_font = DIRECTION_STYLES[row[2]]
    cells[2].fill = indicator_fill
    cells[2].font = cells[3].font = indicator_font
    for index in (0, 2, 4):
        cells[index].alignment = CENTER


def publish_book(outputs, day, tables):
    version = content_hash((3, tables))
    directory = outputs / day.isoformat() / version
    book = directory / f"账户成交汇总_{day}.xlsx"
    descriptor = directory / "attachment.json"
    if directory.exists():
        metadata = json.loads(descriptor.read_text(encoding="utf-8"))
        if not book.is_file() or book.stat().st_size != metadata["size"] or sha256(book) != metadata["sha256"]:
            raise ValueError(f"已归档的 Excel 发生变化，请核对：{book}")
        return book, version, metadata

    directory.parent.mkdir(parents=True, exist_ok=True)
    quantities = (row[3] for _, columns, rows in tables if columns == COLUMNS for row in rows)
    quantity_places = max((max(0, -value.normalize().as_tuple().exponent) for value in quantities), default=0)
    quantity_format = "#,##0" + ("." + "0" * quantity_places if quantity_places else "")
    row_styles = {}
    for title, columns, rows in tables:
        if columns == COLUMNS:
            instruments = dict.fromkeys(row[1] for row in rows)
            bands = {code: BAND_FILLS[index % len(BAND_FILLS)] for index, code in enumerate(instruments)}
            row_styles[title] = partial(style_trade_row, bands)
    with TemporaryDirectory(prefix=".trades-", dir=directory.parent) as temporary:
        staged = Path(temporary)
        staged_book = staged / book.name
        write_book(
            staged_book, tables,
            column_widths={"交易日": 14, "标的": 20, "买卖方向": 14, "变动数量": 17, "币种": 10,
                           "累计成交金额": 23, "成交笔数": 12, "项目": 24, "说明": 72},
            number_formats={"变动数量": quantity_format, "累计成交金额": "#,##0.00", "成交笔数": "#,##0"},
            filter_sheets=(ALL_ACCOUNTS, *ACCOUNTS), row_styles=row_styles,
        )
        metadata = {"size": staged_book.stat().st_size, "sha256": sha256(staged_book)}
        atomic_json(staged / descriptor.name, metadata)
        staged.rename(directory)
    return book, version, metadata


def run_day(day, root, outputs, config_path, bct_script, *, scheduled, recipients=None, wa_output=None):
    day_text = day.isoformat()
    if wa_output is not None:
        recipients = validate_recipients(recipients) if recipients else []
    config_path = config_path or root / "inputs" / "config.local.json"
    config = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.is_file() else {}
    source_root = root / "trade_summary"
    with file_lock(source_root / ".writer.lock", timeout=3):
        print(f"抓取 {day_text} 当日 BCT 流水。", flush=True)
        client = configure_credentials(root, config, bct_script, allow_picker=not scheduled)
        archive_batch(client, source_root, [day_text], {})
        source = source_root / "flows" / f"{day_text}.xlsx"
        rows = read_source(source, "flow", day_text)
        tables, stats = report_tables(day, rows)
        book, version, metadata = publish_book(outputs, day, tables)
        print(f"原始流水：{source}", flush=True)
        print(f"成交汇总：{book}，纳入成交 {stats['trades']:,} 笔。", flush=True)
        warning = ""
        if stats["unassigned"]:
            warning = f"另有 {stats['unassigned']:,} 笔原始成交缺少交易账户，见取数说明。"
            print(warning, flush=True)
        if wa_output is not None:
            body = f"{day_text} 三账户当日成交共 {stats['trades']:,} 笔。按标的和买卖方向汇总，详见附件。{warning}"
            manifest = {
                "delivery_key": "account-trades-" + content_hash((version, recipients)),
                "mail": {"to": recipients, "cc": [], "bcc": [], "subject": f"三账户当日成交汇总 {day_text}",
                         "body": body, "attachments": [{"path": str(book), **metadata}]},
            }
            atomic_json(wa_output, manifest)
            print("邮件结果已交给工作台，入队及投递状态请查看工作台。", flush=True)
        elif scheduled:
            print("工作台未请求邮件结果，本次只生成报表。", flush=True)
    return book


def main(argv=None):
    paths = DataPaths.for_repo(REPO)
    parser = argparse.ArgumentParser(description=TASK_NAME)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--setup", action="store_true", help="设置收件人并登记每天 15:30 任务")
    mode.add_argument("--edit-recipients", action="store_true", help="打开当日成交汇总收件人设置")
    mode.add_argument("--run", action="store_true", help="立即生成当天 Excel")
    parser.add_argument("--set-recipients", help="命令行保存收件人，多个邮箱以逗号分隔")
    parser.add_argument("--data", type=Path, default=paths.root / "account_daily_pnl")
    parser.add_argument("--output", type=Path, default=paths.export("account_trade_summary"))
    parser.add_argument("--config", type=Path, help="既有账户配置")
    parser.add_argument("--bct-script", type=Path, help="既有 BCT 登录来源")
    parser.add_argument("--work-root", type=Path, help="已有工作自动化工作台目录")
    parser.add_argument("--scheduled", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--wa-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    settings_mode = args.setup or args.edit_recipients or args.set_recipients is not None
    if settings_mode and (args.run or args.scheduled or args.wa_output):
        parser.error("收件人设置或登记请单独运行。")
    if args.work_root and not args.setup:
        parser.error("--work-root 用于登记工作台任务。")

    mail_path = REPO / "account_daily_pnl" / MAIL_CONFIG
    try:
        if settings_mode:
            if args.set_recipients is not None:
                recipients = recipients_from_text(args.set_recipients)
            else:
                recipients = edit_recipients(read_recipients(mail_path))
            if recipients is None:
                return 0
            atomic_json(mail_path, {"to": recipients})
            print(f"已保存 {len(recipients)} 位收件人。", flush=True)
            if args.setup:
                work_root = args.work_root.resolve() if args.work_root else find_work_automation(REPO / "account_daily_pnl")
                definition = task_definition(args.data.resolve(), args.output.resolve(), args.config, args.bct_script)
                task, created = register_task(work_root, definition)
                print(f"{'已登记' if created else '已更新'}工作台任务「{task['name']}」，"
                      f"每天 {CLOCK}（北京时间），沿用现有工作台发件账户。", flush=True)
            return 0

        recipients = read_recipients(mail_path) if args.wa_output else None
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        run_day(today, args.data.resolve(), args.output.resolve(), args.config, args.bct_script,
                scheduled=args.scheduled, recipients=recipients, wa_output=args.wa_output)
        return 0
    except Exception as exc:
        print(f"当日成交汇总失败：{exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

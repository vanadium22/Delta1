"""Numeric Excel gets a private configuration copy; existing Apps keep theirs."""
import argparse
import json
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent


def prepare_config(local_root=None, *, module_root=MODULE_ROOT):
    if local_root is not None:
        return Path(local_root).resolve()
    source = Path(module_root) / 'localsetting'
    target = source / 'numeric_excel'
    target.mkdir(parents=True, exist_ok=True)
    for name in ('native.json', 'native_formulas.json'):
        original, copy = source / name, target / name
        if copy.exists() or not original.is_file():
            continue
        raw = original.read_bytes()
        decoded=raw.decode('utf-8-sig')
        json.loads(decoded)  # Fail before copying invalid JSON.
        try:
            with copy.open('xb') as out:
                out.write(decoded.encode('utf8'))
        except FileExistsError:
            pass
    if not (target / 'native.json').exists():
        from dashboard.marketdata.paths import REALTIME_ROOT, DIVIDEND_ROOT
        initial = dict(history_roots=[], reference_file='',
                       dividend_root=str(DIVIDEND_ROOT), realtime_root=str(REALTIME_ROOT))
        try:
            with (target / 'native.json').open('x', encoding='utf8') as out:
                json.dump(initial, out, ensure_ascii=False, indent=2)
        except FileExistsError:
            pass
    return target.resolve()


def problems(config):
    from dashboard.marketdata.repository import MarketDataRepository, ReferenceBook
    issues = []
    roots = config.get('history_roots') or []
    if not roots:
        issues.append('未配置标准化历史；现有 Wind SQLite 不能直接填入 history_roots。')
    for root in roots:
        try:
            report=MarketDataRepository.inspect(root)
            if not report['coverage']:
                issues.append(f'标准化目录尚无已保存行情：{root}')
        except Exception as exc:
            issues.append(f'历史目录不可读或不是标准化数据：{root}（{type(exc).__name__}）')
    reference = config.get('reference_file')
    try:
        if not reference or not Path(reference).is_file():
            raise ValueError('missing reference')
        value = ReferenceBook(reference).data
        if not isinstance(value.get('contracts'),list) or not value['contracts']:
            raise ValueError('empty contracts')
    except (OSError, ValueError, AttributeError):
        issues.append('reference_file 缺失或没有有效合约列表。')
    if not config.get('realtime_root'):
        issues.append('realtime_root 未配置；请在数字版副本中指定独立行情缓存目录。')
    return issues


def main(argv=None):
    parser = argparse.ArgumentParser(description='离线检查数字版配置；默认只创建/使用独立副本，不连接 Wind/VPN。')
    parser.add_argument('--local-root', type=Path)
    args = parser.parse_args(argv)
    from dashboard.native.model import NativeModel
    from dashboard.marketdata.paths import DATA_ROOT
    model = NativeModel(prepare_config(args.local_root))
    try:
        print(f'数字版配置：{model.path}')
        print(f'共享数据根目录：{DATA_ROOT}')
        issues = problems(model.config)
        for issue in issues:
            print('待处理：' + issue)
        dividend_root = model.config.get('dividend_root')
        if not dividend_root or not Path(dividend_root).is_dir():
            print('提示：未找到分红目录；缺失分红相关指标将留空。')
        print('配置检查未通过，参见 dashboard/COMPANY_SETUP.md。' if issues else
              '路径和基本格式检查通过；请先运行 -ReadOnlyCache 核对各行数据时间与缺失原因。')
        return 1 if issues else 0
    finally:
        model.close()


if __name__ == '__main__':
    raise SystemExit(main())

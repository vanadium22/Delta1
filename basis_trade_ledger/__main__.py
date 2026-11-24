import argparse
from pathlib import Path
from time import perf_counter

STARTED = perf_counter()


def main():
    parser = argparse.ArgumentParser(description='基差交易台账')
    parser.add_argument('--data-root', type=Path, help='公共数据根目录')
    parser.add_argument('--startup-check', action='store_true', help='记录首屏和可录入时间后退出')
    args = parser.parse_args()

    from .desktop import LedgerWindow, application
    from .store import Ledger, data_paths

    paths = data_paths(args.data_root)
    app = application()
    window = LedgerWindow(Ledger(paths.root / 'basis_trade_ledger' / 'ledger.sqlite'), paths)
    if args.startup_check:
        window.first_paint.connect(lambda: print(f'first_paint_ms={(perf_counter() - STARTED) * 1000:.1f}', flush=True))

        def report_ready():
            print(f'input_ready_ms={(perf_counter() - STARTED) * 1000:.1f}  '
                  f'groups={len(window.group_rows)}  trades={len(window.rows)}', flush=True)
            app.quit()

        window.input_ready.connect(report_ready)
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())

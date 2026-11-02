"""Offscreen end-to-end validation with a user-selected local job; no network."""
import argparse
from pathlib import Path
import os
from time import monotonic, sleep


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["DELTA1_THEME"] = "public"
    from dashboard.backtest.desktop import BacktestWindow, configure_style
    from dashboard.backtest.io import write_json
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    configure_style(app)
    window = BacktestWindow(config_path=args.config)
    window.resize(1920, 1080)
    window.show()
    args.output.mkdir(parents=True, exist_ok=True)
    window.fields["output_root"].setText(str((args.output / "runs").resolve()))
    window.workers.setValue(2)
    runs = {}
    def wait_idle():
        deadline = monotonic() + 40
        while window.task is not None and monotonic() < deadline:
            app.processEvents()
            sleep(.005)
        app.processEvents()
        if window.task is not None:
            window.cancel()
            raise RuntimeError("Desktop task did not finish within the bounded validation window")
    try:
        for precision in ("1d", "auto"):
            window.precision.setCurrentIndex(window.precision.findData(precision))
            window.run_backtest()
            wait_idle()
            result = window.result
            assert result is not None, window.status.text()
            assert result.metadata["precision"]["requested"] == precision, window.status.text()
            assert result.metadata["market_data"]["load_statistics"]["workers"] == 2
            for account in result.accounts.values():
                assert not account.equity.index.normalize().duplicated().any()
                assert (account.equity.index.hour == 15).all()
            runs[precision] = dict(orders=len(result.actual_orders),
                                   daily_rows=max(len(a.equity) for a in result.accounts.values()),
                                   performance=result.metadata["performance"],
                                   load_statistics=result.metadata["market_data"]["load_statistics"],
                                   output_dir=result.output_paths["output_dir"])
            for width, height in ((1920, 1080), (3840, 2160)):
                window.resize(width, height)
                app.processEvents()
                app.processEvents()
                assert window.grab().save(str(args.output / f"desktop_{precision}_{width}.png"))
                for tab in (0, 1):
                    window.forms.setCurrentIndex(tab)
                    app.processEvents()
                    assert window.forms.currentWidget().horizontalScrollBar().maximum() == 0
            print(f"{precision}: {runs[precision]['orders']} orders, {runs[precision]['daily_rows']} daily equity rows", flush=True)
        write_json(args.output / "ui_validation.local.json", runs)
    finally:
        window.close()
        wait_idle()
        app.processEvents()
        app.quit()


if __name__ == "__main__":
    main()

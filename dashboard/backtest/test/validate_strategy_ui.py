"""Bounded offscreen company/development smoke test using isolated demo inputs."""
import argparse
from pathlib import Path
import os
from time import monotonic, sleep


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from dashboard.backtest.desktop import BacktestWindow, configure_style
    from dashboard.backtest.desktop_strategy import generate_targets
    from dashboard.backtest.io import write_json
    from dashboard.backtest.strategy.examples import demo_market
    from PySide6.QtWidgets import QApplication
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    market, points = demo_market()
    market.close.to_parquet(root / "close.parquet")
    points.to_parquet(root / "points.parquet")
    write_json(root / "reference.json", dict(contracts=list(market.contracts.values())))
    job = dict(data=dict(close_path=str(root / "close.parquet"), reference_path=str(root / "reference.json"),
                         dividend_points_path=str(root / "points.parquet"), margin_rates={"IC": .15}),
               backtest=dict(d0=0), factors=dict(window_days=3), factor_name="basis_percentile",
               cta=dict(transform="center_percentile"), ui=dict(output_root=str(root / "runs")))
    write_json(root / "job.local.json", job)
    app = QApplication([])
    configure_style(app)
    window = BacktestWindow(config_path=root / "job.local.json")
    window.show()
    def idle():
        deadline = monotonic() + 30
        while window.task is not None and monotonic() < deadline:
            app.processEvents()
            sleep(.005)
        app.processEvents()
        assert window.task is None, window.status.text()
    try:
        generate_targets(window)
        idle()
        assert hasattr(window, "strategy_result"), window.status.text()
        window.run_backtest()
        idle()
        assert window.result is not None, window.status.text()
        assert len(window.result.actual_orders) > 0
        assert window.result.metadata["config"]["d0"] == 0
        for width, height in ((1920, 1080), (3840, 2160)):
            window.resize(width, height)
            for tab in range(window.forms.count()):
                window.forms.setCurrentIndex(tab)
                app.processEvents()
                app.processEvents()
                assert window.forms.currentWidget().horizontalScrollBar().maximum() == 0
                if tab in (0, 2):
                    assert window.grab().save(str(root / f"desktop_strategy_tab{tab}_{width}.png"))
        write_json(root / "validation.local.json", dict(test_data="isolated synthetic inputs, no network or Z drive",
                   factor_rows=len(window.strategy_result.targets), actual_orders=len(window.result.actual_orders),
                   d0=0, factor_paths=window.strategy_result.output_paths, backtest_paths=window.result.output_paths))
        print(f"Desktop factor generation -> {len(window.result.actual_orders)} actual orders; 1080p/4K verified")
    finally:
        window.close()
        idle()
        app.processEvents()
        app.quit()


if __name__ == "__main__":
    main()

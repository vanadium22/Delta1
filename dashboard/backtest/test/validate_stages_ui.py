"""Offscreen stage reuse, config recovery and all four pages at 1080p/4K."""
import argparse
import json
import os
from pathlib import Path
from time import monotonic, sleep


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    import pandas as pd
    from dashboard.backtest.__main__ import load_job
    from dashboard.backtest.desktop import BacktestWindow, configure_style
    from dashboard.backtest.desktop_strategy import compute_only, apply_cta_only, read_factor
    from dashboard.backtest.io import frame_fingerprint, write_json
    from dashboard.backtest.synthetic import write_inputs

    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    inputs = write_inputs(root / "inputs")
    job = load_job(inputs / "index_09.local.json")
    job["ui"] = dict(output_root=str(root / "runs"))
    write_json(root / "job.local.json", job)
    app = QApplication.instance() or QApplication([])
    configure_style(app)
    window = BacktestWindow(config_path=root / "job.local.json")
    window.show()

    def idle():
        deadline = monotonic() + 45
        while window.task is not None and monotonic() < deadline:
            app.processEvents()
            sleep(.005)
        app.processEvents()
        assert window.task is None, window.status.text()

    try:
        compute_only(window)
        idle()
        assert window.factor_result is not None, window.status.text()
        before = window.factor_result.continuous_factors["basis_percentile"].copy(deep=True)
        apply_cta_only(window)
        idle()
        first = window.strategy_result
        window.strategy_controls["threshold"].setValue(.8)
        saved = window.job()
        write_json(root / "reopen.local.json", saved)
        window.load_config(root / "reopen.local.json")
        assert window.factor_result is None
        assert window.job()["cta"]["parameters"]["threshold"] == .8
        read_factor(window)
        idle()
        pd.testing.assert_frame_equal(before, window.factor_result.continuous_factors["basis_percentile"], check_freq=False, check_exact=True)
        apply_cta_only(window)
        idle()
        second = window.strategy_result
        assert first.metadata["factor_fingerprint"] == second.metadata["factor_fingerprint"]
        window.run_backtest()
        idle()
        assert window.result is not None, window.status.text()
        assert len(window.result.actual_orders) > 0
        expected = ["数据配置", "因子参数", "CTA 参数", "回测执行参数"]
        assert [window.forms.tabText(i) for i in range(4)] == expected
        pictures = []
        for width, height in ((1920, 1080), (3840, 2160)):
            window.resize(width, height)
            for tab in range(4):
                window.forms.setCurrentIndex(tab)
                app.processEvents()
                app.processEvents()
                assert window.forms.currentWidget().horizontalScrollBar().maximum() == 0
                target = root / f"stages_{width}_tab{tab}.png"
                assert window.grab().save(str(target))
                pictures.append(str(target))
        record = dict(source="synthetic fixtures only; DDB/VPN/Z untouched", pages=expected,
                      factor_fingerprint=frame_fingerprint(before), factor_cells_unchanged=True,
                      reused_thresholds=[.9, .8], config_recovered=True, saved_factor_reloaded=True,
                      actual_orders=len(window.result.actual_orders), accounts=len(window.result.accounts),
                      screenshots=pictures, factor_paths=window.factor_result.output_paths,
                      cta_paths=second.output_paths, backtest_paths=window.result.output_paths)
        write_json(root / "validation.local.json", record)
        print(json.dumps({k: record[k] for k in ("pages", "factor_cells_unchanged", "reused_thresholds", "actual_orders", "accounts")}, ensure_ascii=False))
    finally:
        window.close()
        idle()
        window.close()
        app.processEvents()


if __name__ == "__main__":
    main()

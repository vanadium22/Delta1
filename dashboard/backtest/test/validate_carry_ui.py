"""Offscreen reopening of an explicit local carry study, including linked legs."""
import argparse
import json
import os
from pathlib import Path
from time import monotonic, sleep


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from dashboard.backtest.desktop import BacktestWindow, configure_style
    from dashboard.backtest.io import write_json
    from dashboard.backtest.models import BacktestConfig, BacktestError, check_market_source
    from PySide6.QtWidgets import QApplication
    study = args.study.resolve()
    meta = json.loads((study / "study.json").read_text(encoding="utf-8"))
    check_market_source(meta.get("market", {}))
    if meta.get("invalidated"):
        raise BacktestError("Cannot validate an invalidated study as current evidence")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = QApplication([])
    configure_style(app)
    first_tag = str(meta["config"]["thresholds"][0]).replace(".", "_")
    window = BacktestWindow(config_path=study / f"product_best_{first_tag}/job.local.json")
    window.show()
    reports = {}

    def wait_idle():
        deadline = monotonic() + 30
        while window.task is not None and monotonic() < deadline:
            app.processEvents()
            sleep(.005)
        app.processEvents()
        if window.task is not None:
            window.cancel()
            raise RuntimeError("Desktop load did not finish within the validation window")

    try:
        for selection in ("product_best", "contract_independent"):
            for threshold in meta["config"]["thresholds"]:
                name = f"{selection}_{str(threshold).replace('.', '_')}"
                directory = study / name
                window.load_config(directory / "job.local.json")
                job = window.job()
                config = BacktestConfig(**job["backtest"])
                assert config.hedges and config.rebalance_on_change_only
                assert config.mode == ("product" if selection == "product_best" else "contract_pair")
                window.open_result(directory)
                wait_idle()
                result = window.result
                assert result is not None and Path(result.output_paths["output_dir"]) == directory, window.status.text()
                for account in result.accounts.values():
                    for root in ("IF", "IH", "IC", "IM"):
                        primary = [s for s in account.positions if s.startswith(root) and s.endswith(".CFE")]
                        if primary:
                            ratio = 300 if root in ("IF", "IH") else 200
                            assert account.positions[root+"_spot"].eq(-ratio*account.positions[primary].sum(axis=1)).all()
                for account_name in (window.account.itemText(0), window.account.itemText(window.account.count()-1)):
                    window.account.setCurrentText(account_name)
                    for tab in range(window.tables.count()):
                        window.tables.setCurrentIndex(tab)
                        window.refresh_table()
                        app.processEvents()
                for width, height in ((1920, 1080), (3840, 2160)):
                    window.resize(width, height)
                    for tab in range(window.forms.count()):
                        window.forms.setCurrentIndex(tab)
                        app.processEvents()
                        assert window.forms.currentWidget().horizontalScrollBar().maximum() == 0
                    window.forms.setCurrentIndex(0)
                    for tab in range(window.tables.count()):
                        if window.tables.widget(tab).objectName() == "actual_orders":
                            window.tables.setCurrentIndex(tab)
                    app.processEvents()
                    assert window.grab().save(str(output / f"{name}_{width}.png"))
                reports[name] = dict(accounts=len(result.accounts), orders=len(result.actual_orders),
                                     config_roundtrip=True, tables_reopened=True, hedge_quantities_match=True)
                print(f"{name}: {len(result.accounts)} accounts, all tables/config/hedges verified", flush=True)
        write_json(output / "validation.local.json", dict(study=str(study), coverage_status=meta["coverage_status"],
                   desktop_offscreen=True, resolutions=["1920x1080", "3840x2160"], runs=reports))
    finally:
        window.close()
        wait_idle()
        app.processEvents()
        app.quit()


if __name__ == "__main__":
    main()

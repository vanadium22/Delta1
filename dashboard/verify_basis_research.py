"""Offline verification, local publication, and optional screenshot of pair research."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "data/ddb_basis/verification")
    parser.add_argument("--captures", action="store_true")
    args = parser.parse_args()
    from .native.developer_model import DeveloperModel
    from .native.publication import decode_state
    args.output.mkdir(parents=True, exist_ok=True)
    model = DeveloperModel()
    try:
        state = model.snapshot(dict(product="IC", frequency="1d", demo=False, save=False))
        if state.get("publish_error"):
            raise RuntimeError(state["publish_error"])
        audit = dict(versions=state["versions"], reference_version=state["reference_version"],
                     source_roots=model.config["history_roots"], publish_root=str(model.publish_root),
                     frequencies={})
        for frequency in ("1d", "1m", "1s"):
            value = model._bundle["views"]["IC:" + frequency]
            research = decode_state(value).get("pair_research", {})
            rows = research.get("cross", [])
            errors = [abs(r["futures_change5"]-r["spot_change5"]-r["basis_change5"])
                      for r in rows if all(r.get(k) is not None for k in ("futures_change5", "spot_change5", "basis_change5"))]
            if errors and max(errors) > 1e-7:
                raise AssertionError("Futures / spot / basis decomposition mismatch")
            audit["frequencies"][frequency] = dict(time=research.get("time"),
                counts={k:len(research.get(k, [])) for k in ("basis", "calendar", "cross")},
                cross_with_z=sum(r.get("z") is not None for r in rows),
                cross_with_beta=sum(r.get("beta") is not None for r in rows),
                max_decomposition_error_bp=max(errors) if errors else None)
            (args.output / ("research_"+frequency+".json")).write_text(json.dumps(research, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        (args.output / "verification.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        print(json.dumps(audit, ensure_ascii=False, indent=2), flush=True)
        if args.captures:
            os.environ["QT_QPA_PLATFORM"] = "offscreen"
            from .native.bootstrap import configure_qt
            configure_qt()
            from PySide6.QtWidgets import QApplication
            from .native.basis_panel import BasisResearchPanel
            from .native.widgets import STYLE
            app = QApplication([])
            from .native.app import configure_style
            configure_style(app)
            from .native.app import configure_style
            configure_style(app)
            panel = BasisResearchPanel()
            panel.setStyleSheet(STYLE)
            panel.resize(1280, 770)
            panel.render(state["pair_research"])
            panel.show()
            for i, category in enumerate(("basis", "calendar", "cross")):
                panel.tabs.setCurrentIndex(i)
                if category == "calendar":
                    panel.tables[category].setCurrentCell(1,0)
                if category == "cross":
                    # IF/IC December: useful distinction between price and basis.
                    index = next((j for j,r in enumerate(panel.rows[category]) if r["id"] == "IF2612.CFE/IC2612.CFE"),0)
                    panel.tables[category].setCurrentCell(index,0)
                app.processEvents()
                if not panel.grab().save(str(args.output / (category+".png"))):
                    raise RuntimeError("Screenshot save failed")
            panel.close()
    finally:
        model.close()


if __name__ == "__main__":
    main()

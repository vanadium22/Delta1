"""Factor/CTA controls inside the existing local desktop window."""
from dataclasses import asdict
from pathlib import Path

from PySide6.QtWidgets import QLineEdit, QSpinBox

from .models import DataConfig
from .strategy import CTAConfig, FactorConfig, StrategyDataConfig, generate_strategy


def build_strategy_page(window):
    from .desktop import button, combo, label, spin
    form = window.page("因子与CTA")
    controls = window.strategy_controls = {}
    controls["factor_name"] = combo([("去分红年化基差 · 百分点", "annual_basis"), ("年化基差历史分位 · 0—1", "basis_percentile")])
    controls["factor_name"].setCurrentIndex(1)
    form.addRow("策略使用的因子 · 同时导出两个示例", controls["factor_name"])
    controls["roots"] = QLineEdit("IC")
    controls["slots"] = QLineEdit("00,01,02,03")
    form.addRow("品种 · 逗号分隔", controls["roots"])
    form.addRow("计算档位 · 目标和因子自动落实际合约", controls["slots"])
    for key, title, default in (("window_days", "分位历史交易日窗口 · 排除当日", 20),
                                ("min_annual_days", "年化有效最小剩余自然日", 5),
                                ("min_samples", "分位窗口最少有效样本", 2),
                                ("lookback_window", "Z 值历史交易日窗口 · 排除当日", 20)):
        item = QSpinBox()
        item.setRange(1 if key in {"min_annual_days", "min_samples"} else 2, 5000)
        item.setValue(default)
        controls[key] = item
        form.addRow(title, item)
    controls["mode"] = combo([("固定阈值", "fixed"), ("历史 Z 值阈值", "zscore")])
    controls["direction"] = combo([("正值开多、负值开空", 1), ("反向交易", -1)])
    form.addRow("开平仓模式", controls["mode"])
    form.addRow("交易方向", controls["direction"])
    controls["transform"] = combo([("原始因子值", "identity"), ("分位映射为 2p−1", "center_percentile")])
    controls["transform"].setCurrentIndex(1)
    controls["missing"] = combo([("输出零目标", "flat"), ("保持状态", "hold"), ("报错", "error")])
    form.addRow("因子值转换", controls["transform"])
    form.addRow("缺失因子处理", controls["missing"])
    def factor_changed():
        value = "center_percentile" if controls["factor_name"].currentData() == "basis_percentile" else "identity"
        controls["transform"].setCurrentIndex(controls["transform"].findData(value))
    controls["factor_name"].currentIndexChanged.connect(factor_changed)
    for key, title, default in (("open_threshold", "固定开仓绝对阈值", .7), ("close_threshold", "固定平仓绝对阈值", .2),
                                ("z_open", "Z 开仓绝对阈值", 2), ("z_close", "Z 平仓绝对阈值", .4),
                                ("weight", "每档目标资金占用 · %", 20)):
        item = spin(default, maximum=100 if key == "weight" else 100000, minimum=0, decimals=4)
        controls[key] = item
        form.addRow(title, item)
    sources = window.strategy_sources = {}
    for key, title, directory in (("dividend_store_root", "逐日合约分红缓存目录 · 可选", True),
                                   ("dividend_records_path", "逐日分红版本 JSON · 可选", False),
                                   ("calendar_path", "交易日历 CSV/JSON · 可选", False)):
        sources[key] = window.path_row(form, title, key, directory=directory)
        window.fields.pop(key)
    note = label("复用“行情与参数”的价格、参考和分红调整表。分位先变为 2p−1；中间档位只用于计算，输出为实际合约。", "muted")
    note.setWordWrap(True)
    form.addRow(note)
    form.addRow(button("生成因子与目标表", lambda: generate_targets(window), primary=True))


def strategy_settings(window):
    c = window.strategy_controls
    factors = FactorConfig(roots=tuple(s.strip().upper() for s in c["roots"].text().split(",") if s.strip()),
                           slots=tuple(int(s.strip()) for s in c["slots"].text().split(",") if s.strip()),
                           window_days=c["window_days"].value(), min_annual_days=c["min_annual_days"].value(),
                           min_samples=c["min_samples"].value(),
                           precision=window.precision.currentData(), workers=window.workers.value())
    name = c["factor_name"].currentData()
    cta = CTAConfig(mode=c["mode"].currentData(), direction=c["direction"].currentData(),
                    open_threshold=c["open_threshold"].value(), close_threshold=c["close_threshold"].value(),
                    lookback_window=c["lookback_window"].value(), z_open=c["z_open"].value(), z_close=c["z_close"].value(),
                    position_weight=c["weight"].value() / 100,
                    transform=c["transform"].currentData(), missing=c["missing"].currentData())
    source = StrategyDataConfig(**{k: field.text().strip() or None for k, field in window.strategy_sources.items()})
    return dict(factors=asdict(factors), cta=asdict(cta), strategy_data=asdict(source), factor_name=name)


def apply_strategy_settings(window, job):
    c = window.strategy_controls
    factors = FactorConfig(**job.get("factors", {}))
    cta = CTAConfig(**job.get("cta", {}))
    c["roots"].setText(",".join(factors.roots))
    c["slots"].setText(",".join(f"{s:02}" for s in factors.slots))
    for key in ("window_days", "min_annual_days", "min_samples"):
        c[key].setValue(getattr(factors, key))
    for key in ("open_threshold", "close_threshold", "lookback_window", "z_open", "z_close"):
        c[key].setValue(getattr(cta, key))
    c["weight"].setValue(cta.position_weight * 100)
    for key, value in (("mode", cta.mode), ("direction", cta.direction), ("factor_name", job.get("factor_name", "basis_percentile"))):
        c[key].setCurrentIndex(c[key].findData(value))
    transform = job.get("cta", {}).get("transform", "center_percentile" if c["factor_name"].currentData() == "basis_percentile" else "identity")
    for key, value in (("transform", transform), ("missing", cta.missing)):
        c[key].setCurrentIndex(c[key].findData(value))
    for key, field in window.strategy_sources.items():
        field.setText(str(job.get("strategy_data", {}).get(key) or ""))


def generate_targets(window):
    try:
        job = window.job()
        settings = strategy_settings(window)
        output = Path(job["output_dir"]).with_name("strategy_" + Path(job["output_dir"]).name)
        def run(cancel, progress):
            progress(dict(stage="instructions", message="正在生成连续档位因子与实际合约目标"))
            return generate_strategy(data_config=DataConfig(**job["data"]),
                                     source_config=StrategyDataConfig(**settings["strategy_data"]),
                                     factor_config=FactorConfig(**settings["factors"]), cta_config=CTAConfig(**settings["cta"]),
                                     factor_name=settings["factor_name"], start=job["backtest"]["start"], end=job["backtest"]["end"],
                                     output_dir=output, cancel_event=cancel, progress=progress)
        def complete(result):
            window.strategy_result = result
            window.fields["instructions_path"].setText(result.output_paths["targets"])
            valid = result.metadata["quality"][settings["factor_name"]]["valid_cells"]
            note = "；" + "；".join(result.metadata["warnings"]) if result.metadata["warnings"] else "；可检查数据并回测"
            window.show_status(f"已生成 {len(result.targets):,} 行实际合约目标；所选因子有效值 {valid:,} 个，目标路径已填入{note}。")
        window.submit(run, complete)
    except (ValueError, TypeError, OSError) as exc:
        window.show_error(str(exc))

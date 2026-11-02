"""Separate factor and CTA pages, including independent saved-stage actions."""
from dataclasses import asdict
from pathlib import Path

from PySide6.QtWidgets import QLineEdit, QSpinBox

from .configuration import CTA_SCHEMAS, FACTOR_SCHEMAS, CTASpec, FactorSpec, cta_spec, factor_spec
from .strategy import load_factors
from .workflow import cta_stage, factor_stage


def build_strategy_page(window):
    from .desktop import button, combo, label, spin
    factor_form = window.page("因子参数")
    cta_form = window.page("CTA 参数")
    c = window.strategy_controls = {}
    c["factor_name"] = combo([("去分红年化基差 · 百分点", "annual_basis"),
        ("年化基差历史分位 · 原始 p", "basis_percentile"), ("F−指数价差历史分位 · 原始 p", "price_basis_percentile"),
        ("01−03 跨期价差历史分位 · 原始 p", "calendar_spread_percentile"), ("连续合约 close 历史分位 · 原始 p", "close_percentile")])
    c["factor_name"].setCurrentIndex(1)
    factor_form.addRow("因子函数", c["factor_name"])
    c["roots"], c["slots"] = QLineEdit("IC"), QLineEdit("00,01,02,03")
    factor_form.addRow("品种 · 逗号分隔", c["roots"])
    factor_form.addRow("计算与映射审计档位", c["slots"])
    for key, title, default in (("window_days", "历史窗口 · 前 N 个交易日，排除当日", 60),
                               ("min_annual_days", "年化最小剩余自然日", 5), ("min_samples", "最少有效历史样本", 2)):
        item = QSpinBox()
        item.setRange(1 if key != "window_days" else 2, 5000)
        item.setValue(default)
        c[key] = item
        factor_form.addRow(title, item)
    c["factor_precision"] = combo([("日线", "1d"), ("原始观测时点", "auto")])
    c["factor_workers"] = QSpinBox()
    c["factor_workers"].setRange(0, 64)
    factor_form.addRow("因子计算频率", c["factor_precision"])
    factor_form.addRow("因子读取进程 · 0 自动", c["factor_workers"])
    note = label("因子只计算数值；分位输出 p∈[0,1]。保存后可反复用于不同 CTA。", "muted")
    note.setWordWrap(True)
    factor_form.addRow(note)
    factor_form.addRow(button("单独计算并保存因子", lambda: compute_only(window), primary=True))

    c["cta_name"] = combo([("固定阈值", "fixed"), ("Z 阈值", "zscore"),
        ("指数对冲 · 择优/独立持有到期", "expiry_index"), ("01−03 跨期 · 到期双平", "expiry_spread")])
    c["mode"] = c["cta_name"]
    cta_form.addRow("CTA 函数", c["cta_name"])
    c["input_factor"] = combo([(name, name) for name in FACTOR_SCHEMAS])
    c["input_factor"].setCurrentIndex(1)
    cta_form.addRow("CTA 输入因子", c["input_factor"])
    window.factor_input = window.path_row(cta_form, "已保存因子目录 · 留空使用内存因子", "factor_input", directory=True)
    window.fields.pop("factor_input")
    cta_form.addRow(button("读取已保存因子", lambda: read_factor(window)))
    c["direction"] = combo([("正向", 1), ("反向 / 反转", -1)])
    c["transform"] = combo([("原始值", "identity"), ("显式 2p−1", "center_percentile")])
    c["transform"].setCurrentIndex(1)
    c["missing"] = combo([("输出零目标", "flat"), ("保持状态", "hold"), ("报错", "error")])
    c["hedge"] = combo([("单腿", "none"), ("等权反向指数腿 · 权重和=0", "index")])
    c["selection"] = combo([("四档绝对值择优", "product_best"), ("各实际合约独立", "contract_independent")])
    c["candidate_slots"] = QLineEdit("00,01,02,03")
    for key, title in (("direction", "交易方向"), ("transform", "因子变换"), ("missing", "缺失分数"),
                       ("hedge", "目标对冲"), ("selection", "持有到期择约"), ("candidate_slots", "择约候选档位")):
        cta_form.addRow(title, c[key])
    for key, title, default in (("open_threshold", "固定开仓绝对阈值", .7), ("close_threshold", "固定平仓绝对阈值", .2),
        ("z_open", "Z 开仓阈值", 2), ("z_close", "Z 平仓阈值", .4), ("threshold", "到期开仓阈值 · abs(2p−1)", .9),
        ("weight", "目标权重 · % / 每腿", 20)):
        c[key] = spin(default, maximum=100 if key == "weight" else 100000, minimum=0, decimals=4)
        cta_form.addRow(title, c[key])
    c["lookback_window"] = QSpinBox()
    c["lookback_window"].setRange(2, 5000)
    c["lookback_window"].setValue(20)
    cta_form.addRow("Z 窗口 · 前 N 个交易日", c["lookback_window"])
    note = label("等权对冲使用合约等价手数权重，资金按价格×乘数×保证金率占用。持有到期锁定实际代码，换档不会换月。", "muted")
    note.setWordWrap(True)
    cta_form.addRow(note)
    cta_form.addRow(button("仅运行 CTA 并保存权重", lambda: apply_cta_only(window), primary=True))
    cta_form.addRow(button("计算因子并运行 CTA", lambda: generate_targets(window)))
    window.strategy_sources = {}

    def changed():
        name = c["factor_name"].currentData()
        c["input_factor"].setCurrentIndex(c["input_factor"].findData(name))
        c["transform"].setCurrentIndex(1 if name.endswith("percentile") else 0)
        for key in ("window_days", "min_annual_days", "min_samples"):
            factor_form.setRowVisible(c[key], key in FACTOR_SCHEMAS[name]["parameters"])
    c["factor_name"].currentIndexChanged.connect(changed)

    def cta_changed():
        name = c["cta_name"].currentData()
        active = CTA_SCHEMAS[name]["parameters"]
        for key in ("open_threshold", "close_threshold", "lookback_window", "z_open", "z_close", "threshold", "selection", "hedge", "missing"):
            cta_form.setRowVisible(c[key], key in active)
        cta_form.setRowVisible(c["candidate_slots"], name == "expiry_index")
        c["transform"].setEnabled(not name.startswith("expiry"))
        if name.startswith("expiry"):
            c["direction"].setCurrentIndex(1)
            c["transform"].setCurrentIndex(1)
            c["weight"].setValue(49.5)
    c["cta_name"].currentIndexChanged.connect(cta_changed)
    changed()
    cta_changed()


def strategy_settings(window):
    c = window.strategy_controls
    name = c["factor_name"].currentData()
    factor = FactorSpec(name=name, parameters={k: c[k].value() for k in FACTOR_SCHEMAS[name]["parameters"]},
        roots=tuple(s.strip().upper() for s in c["roots"].text().split(",") if s.strip()),
        slots=tuple(int(s.strip()) for s in c["slots"].text().split(",") if s.strip()),
        precision=c["factor_precision"].currentData(), workers=c["factor_workers"].value())
    name = c["cta_name"].currentData()
    values = {}
    for key in CTA_SCHEMAS[name]["parameters"]:
        if key == "position_weight":
            values[key] = c["weight"].value() / 100
        elif key == "slots":
            values[key] = tuple(int(v.strip()) for v in c["candidate_slots"].text().split(",") if v.strip())
        else:
            widget = c[key]
            values[key] = widget.currentData() if hasattr(widget, "currentData") else widget.value()
    cta = CTASpec(name=name, input_factor=c["input_factor"].currentData(), parameters=values)
    return dict(factor=asdict(factor), cta=asdict(cta), factor_input=window.factor_input.text().strip() or None)


def apply_strategy_settings(window, job):
    c = window.strategy_controls
    factor, cta = factor_spec(job), cta_spec(job)
    c["factor_name"].setCurrentIndex(c["factor_name"].findData(factor.name))
    c["cta_name"].setCurrentIndex(c["cta_name"].findData(cta.name))
    c["input_factor"].setCurrentIndex(c["input_factor"].findData(cta.input_factor))
    c["roots"].setText(",".join(factor.roots))
    c["slots"].setText(",".join(f"{s:02}" for s in factor.slots))
    c["factor_precision"].setCurrentIndex(c["factor_precision"].findData(factor.precision))
    c["factor_workers"].setValue(factor.workers)
    for key, value in factor.parameters.items():
        c[key].setValue(value)
    for key, value in cta.parameters.items():
        if key == "position_weight":
            c["weight"].setValue(value * 100)
        elif key == "slots":
            c["candidate_slots"].setText(",".join(f"{s:02}" for s in value))
        elif hasattr(c[key], "findData"):
            c[key].setCurrentIndex(c[key].findData(value))
        else:
            c[key].setValue(value)
    window.factor_input.setText(str(job.get("factor_input") or ""))


def _set_signals(window, signals):
    window.strategy_result = signals
    window.fields["instructions_path"].setText(signals.output_paths["targets"])
    required = signals.metadata.get("required_backtest_options", {})
    if required.get("weight_mode"):
        window.weight_mode.setCurrentIndex(window.weight_mode.findData(required["weight_mode"]))
    if required.get("rebalance_on_change_only"):
        window.on_change.setChecked(True)
    if "d0" in required:
        window.expiry_enabled.setChecked(True)
        window.d0.setValue(required["d0"])
    window.show_status(f"CTA 已生成 {len(signals.targets):,} 行实际合约权重，目标路径已填入；可检查并回测。")


def read_factor(window):
    try:
        path = window.factor_input.text().strip()
        if not path:
            raise ValueError("请设置已保存因子目录")
        def complete(result):
            window.factor_result = result
            _display_inputs(window, result)
            window.show_status("因子已读取并校验，可修改 CTA 参数后直接生成权重。")
        window.submit(lambda cancel, progress: load_factors(path, cancel_event=cancel), complete)
    except (ValueError, TypeError, OSError) as exc:
        window.show_error(str(exc))


def compute_only(window):
    try:
        job = window.job()
        output = Path(job["output_dir"]).with_name("factor_" + Path(job["output_dir"]).name)
        def complete(result):
            window.factor_result = result
            _display_inputs(window, result)
            window.factor_input.setText(result.output_paths["output_dir"])
            name = job["factor"]["name"]
            valid = result.metadata["quality"][name]["valid_cells"]
            window.show_status(f"因子已独立保存：{output}；有效值 {valid:,}，可复用不同 CTA。")
        window.submit(lambda cancel, progress: factor_stage(job, output_dir=output, cancel_event=cancel, progress=progress), complete)
    except (ValueError, TypeError, OSError) as exc:
        window.show_error(str(exc))


def apply_cta_only(window):
    try:
        job = window.job()
        factors = job.get("factor_input") or getattr(window, "factor_result", None)
        if factors is None:
            raise ValueError("请先计算或读取因子")
        output = Path(job["output_dir"]).with_name("cta_" + Path(job["output_dir"]).name)
        window.submit(lambda cancel, progress: cta_stage(factors, job, output_dir=output, cancel_event=cancel),
                      lambda result: _set_signals(window, result))
    except (ValueError, TypeError, OSError) as exc:
        window.show_error(str(exc))


def generate_targets(window):
    try:
        job = window.job()
        output = Path(job["output_dir"]).with_name("strategy_" + Path(job["output_dir"]).name)
        def run(cancel, progress):
            factors = factor_stage(job, output_dir=output / "factor", cancel_event=cancel, progress=progress)
            signals = cta_stage(factors, job, output_dir=output / "cta", cancel_event=cancel)
            return factors, signals
        def complete(results):
            factors, signals = results
            window.factor_result = factors
            _display_inputs(window, factors)
            window.factor_input.setText(factors.output_paths["output_dir"])
            _set_signals(window, signals)
        window.submit(run, complete)
    except (ValueError, TypeError, OSError) as exc:
        window.show_error(str(exc))


def _display_inputs(window, factors):
    from .desktop_service import data_manifest_text
    source = factors.metadata.get("market", {})
    window.data_manifest_view.setPlainText(data_manifest_text(source))

"""Calendar-month display profiles, independently saved for figures and Word."""
import re


WINDOW_FIELDS = {
    "series_months": ("常规时序图", 3, 1),
    "fixed_60_months": ("60日固定期限曲线 两个窗口", [3, 1], 2),
    "fixed_90_months": ("90日固定期限曲线 两个窗口", [3, 1], 2),
    "calendar_months": ("跨期曲线（点数/年化）", 3, 1),
    "annual_quantile_months": ("单合约年化分位", [3, 6, 12], 3),
    "fixed_60_quantile_months": ("60日固定期限分位", [3, 6, 12], 3),
    "fixed_90_quantile_months": ("90日固定期限分位", [3, 6, 12], 3),
    "calendar_quantile_months": ("跨期分位（点数/年化）", [3, 6, 12], 3),
    "cross_quantile_months": ("IM与IC基差差分位", [3, 6, 12], 3),
}


def normalize_windows(values=None):
    if values is not None and not isinstance(values, dict):
        raise ValueError("时间窗口设置必须按图表类别填写")
    values = values or {}
    if set(values) - set(WINDOW_FIELDS):
        raise ValueError("存在未知的图表时间窗口")
    result = {}
    for key, (label, default, count) in WINDOW_FIELDS.items():
        raw = values.get(key, default)
        parts = raw
        if isinstance(raw, str):
            text = raw.strip().replace("，", ",").replace("、", ",")
            parts = [p.strip() for p in text.split(",")] if "," in text else text.split()
        parts = list(parts) if isinstance(parts, (list, tuple)) else [parts]
        if not parts or any(isinstance(p, bool) or not re.fullmatch(r"[0-9]+", str(p)) for p in parts):
            raise ValueError(f"{label}：请输入1至36的整数月份，用逗号分隔")
        months = [int(p) for p in parts]
        if any(m < 1 or m > 36 for m in months) or len(set(months)) != len(months):
            raise ValueError(f"{label}：月份须在1至36之间，且不能重复")
        if (count < 3 and len(months) != count) or (count == 3 and not 1 <= len(months) <= 3):
            raise ValueError(f"{label}：请填写{'1至3' if count == 3 else count}个窗口")
        result[key] = months[0] if count == 1 else sorted(months, reverse=count == 2)
    return result


def required_history_months(windows):
    return max(m for value in normalize_windows(windows).values()
               for m in (value if isinstance(value, list) else [value]))


def month_labels(months, separator="、"):
    return separator.join(str(int(m)) for m in months)


def chart_series_months(name, windows):
    if "分位" in name:
        return None
    fixed = re.fullmatch(r"(?:60|90)天固定期限_近(\d+)个月", name)
    if fixed:
        return int(fixed.group(1))
    return windows["calendar_months"] if name.startswith("跨期") else windows["series_months"]


def chart_window_label(name, windows):
    windows = normalize_windows(windows)
    months = chart_series_months(name, windows)
    if months:
        return f"曲线近{months}个自然月"
    key = ("fixed_60_quantile_months" if name.startswith("60天") else
           "fixed_90_quantile_months" if name.startswith("90天") else
           "calendar_quantile_months" if name.startswith("跨期") else
           "cross_quantile_months" if name.startswith("IM_IC_") else "annual_quantile_months")
    return f"分位窗口{month_labels(windows[key], '/')}个自然月，不含截止日"


def window_summary(windows):
    w = normalize_windows(windows)
    return (f"常规曲线{w['series_months']}月；60日曲线{month_labels(w['fixed_60_months'], '/')}月，"
            f"90日曲线{month_labels(w['fixed_90_months'], '/')}月；"
            f"60日分位{month_labels(w['fixed_60_quantile_months'], '/')}月，"
            f"90日分位{month_labels(w['fixed_90_quantile_months'], '/')}月；"
            f"跨期曲线{w['calendar_months']}月，分位{month_labels(w['calendar_quantile_months'], '/')}月")

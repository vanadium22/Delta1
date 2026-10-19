"""Presentation contract for this application build."""
RELEASE_NAME="1.0"
MODULE_TITLES=("股指期货概览","专题与自定义指标","市场异动")
FREQUENCY_OPTIONS=(("1d","日频"),("1m","分钟"),("1s","秒级"))
SHOW_SPECIAL=True
SHOW_EVENTS=True
SHOW_DETAIL=True
SHOW_EVENT_DETAIL=True
AUTO_REFRESH=True
FRAME_NAMES=("spread","basis","near","far","spot","regression")
VALUE_NAMES=("spread","basis_bp","zscore","realized_bp","percentile")
ANALYTIC_NAMES=("calendar_bp","calendar_z","basis_z","beta","r_squared","residual_bp","residual_z","samples","window","reasons","carry")
MATRIX_TITLE="四品种指标矩阵 · 回归使用前 30 个同步收益"
OVERVIEW_TEXT="IF / IH / IC / IM · 价格、基差、跨期与回归同屏观察"
METRIC_ROWS=(("近月价格","near_price","点"),("期现基差 · 期货 / 指数 − 1","basis_bp","bp"),
    ("跨期价差 · 近月 − 远月","calendar_bp","bp"),("跨期偏离 Z · 前 30 根","calendar_z","σ"),
    ("期货对指数收益 β","beta","倍"),("回归解释度 R²","r_squared","0–1"),
    ("当前回归残差 Z","residual_z","σ"),("连续 30 根实现波动","realized_bp","bp"))
CHART_OPTIONS=(("期现基差 / bp","basis","value",False),("窗口收益 / bp","near","close",True),
    ("跨期价差 / bp","spread","value",False),("回归残差 / bp","regression","value",False))

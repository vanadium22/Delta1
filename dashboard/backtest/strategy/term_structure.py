"""Previous-date-only conditional quantiles of annual basis across a root's curve."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..models import BacktestError, check_cancelled
from ..parallel import process_map, worker_cancel_event


@dataclass(frozen=True)
class TermStructureConfig:
    window_days: int = 60
    min_training_samples: int = 120
    degree: int = 1
    quantiles: tuple = (.05, .10, .25, .50, .75, .90, .95)

    def __post_init__(self):
        if type(self.window_days) is not int or self.window_days < 2:
            raise BacktestError("Quantile regression window_days must be integer >=2")
        if type(self.min_training_samples) is not int or self.min_training_samples < 3:
            raise BacktestError("Quantile regression min_training_samples must be integer >=3")
        if type(self.degree) is not int or self.degree not in {1, 2}:
            raise BacktestError("Quantile regression degree must be 1 or 2")
        q = np.asarray(self.quantiles, dtype=float)
        if q.ndim != 1 or len(q) < 3 or len(q) > 19 or not np.isfinite(q).all() or not (np.diff(q) > 0).all() or not (0 < q[0] < q[-1] < 1) or .5 not in q:
            raise BacktestError("quantiles must be 3..19 increasing probabilities in (0,1), including .5")


def fit_quantiles(x, y, quantiles):
    """Exact check-loss LP: X beta + u - v = y, u,v >=0; beta free."""
    from scipy.optimize import linprog
    from scipy.sparse import csr_matrix, eye, hstack
    n, k = x.shape
    eq = hstack([csr_matrix(x), eye(n, format="csr"), -eye(n, format="csr")], format="csr")
    betas, objectives = [], []
    for probability in quantiles:
        check_cancelled(worker_cancel_event())
        cost = np.r_[np.zeros(k), np.full(n, probability), np.full(n, 1-probability)]
        fit = linprog(cost, A_eq=eq, b_eq=y, bounds=[(None, None)] * k + [(0, None)] * (2*n), method="highs-ds")
        if not fit.success:
            raise BacktestError(f"Quantile LP failed: {fit.message}")
        betas.append(fit.x[:k])
        objectives.append(float(fit.fun))
    return np.asarray(betas), objectives


def conditional_rank(value, predictions, probabilities):
    """Monotone rearrangement; coincident fitted quantiles receive mean rank."""
    values = np.sort(np.asarray(predictions, dtype=float))
    unique, inverse = np.unique(values, return_inverse=True)
    levels = np.bincount(inverse, weights=probabilities) / np.bincount(inverse)
    return float(np.interp(value, unique, levels, left=0., right=1.)), values


def quantile_key(probability):
    """Keep familiar permille names; arbitrary valid probabilities must not collide."""
    scaled=float(probability)*1000
    label=f"{round(scaled):03d}" if abs(scaled-round(scaled))<1e-10 else repr(float(probability)).replace(".","p").replace("-","m")
    return "term_structure_q"+label


def _root_models(task):
    root, annual, days, min_days, config = task
    index = annual.index
    output = pd.DataFrame(np.nan, index=index, columns=annual.columns)
    fitted = {quantile_key(q): output.copy() for q in config.quantiles}
    audits = []
    for i in range(config.window_days, len(index)):
        check_cancelled(worker_cancel_event())
        old_y = annual.iloc[i-config.window_days:i].to_numpy().ravel()
        old_days = days.iloc[i-config.window_days:i].to_numpy().ravel()
        skip = np.isfinite(old_days) & (old_days < min_days)
        finite = np.isfinite(old_y) & np.isfinite(old_days) & (old_days >= min_days)
        missing = ~finite & ~skip
        base = dict(timestamp=index[i], root=root, train_start=index[i-config.window_days], train_end=index[i-1],
                    training_samples=int(finite.sum()), missing_observations=int(missing.sum()))
        if missing.any() or finite.sum() < config.min_training_samples:
            audits.append(dict(base, status="missing_history" if missing.any() else "insufficient_samples"))
            continue
        tx = old_days[finite] / 365
        mean, scale = float(tx.mean()), float(tx.std())
        if scale < 1e-12:
            audits.append(dict(base, status="constant_maturity"))
            continue
        train = np.vander((tx-mean)/scale, N=config.degree+1, increasing=True)
        if np.linalg.matrix_rank(train) < config.degree+1:
            audits.append(dict(base, status="rank_deficient"))
            continue
        betas, objectives = fit_quantiles(train, old_y[finite], config.quantiles)
        now_days = days.iloc[i].to_numpy()
        present = annual.iloc[i].to_numpy()
        valid = np.isfinite(present) & np.isfinite(now_days) & (now_days >= min_days)
        now = np.vander((np.where(valid, now_days, mean*365)/365 - mean)/scale, N=config.degree+1, increasing=True)
        predicted = now @ betas.T
        crossing = int((np.diff(predicted[valid], axis=1) < -1e-9).any(axis=1).sum())
        for j in np.flatnonzero(valid):
            rank, ordered = conditional_rank(present[j], predicted[j], config.quantiles)
            output.iat[i, j] = rank
            for q, value in zip(config.quantiles, ordered):
                fitted[quantile_key(q)].iat[i, j] = value
        for q, beta, objective in zip(config.quantiles, betas, objectives):
            audits.append(dict(base, quantile=q, status="fit", term_years_mean=mean, term_years_scale=scale,
                crossing_contracts=crossing, objective=objective, **{f"beta{j}":float(value) for j, value in enumerate(beta)}))
    return output, fitted, pd.DataFrame(audits, columns=list(dict.fromkeys(
        ["timestamp","root","train_start","train_end","training_samples","missing_observations","status","quantile",
         "term_years_mean","term_years_scale","crossing_contracts","objective"] + [f"beta{j}" for j in range(config.degree+1)])))


def term_structure_percentile(panel, annual, config, parameters, *, cancel_event=None, progress=None):
    if panel.close.index.normalize().duplicated().any():
        raise BacktestError("Term-structure quantile regression currently requires daily observations")
    model = TermStructureConfig(**{"window_days":config.window_days,
        **{k:parameters[k] for k in ("window_days", "min_training_samples", "degree", "quantiles") if k in parameters}})
    jobs = []
    for root in config.roots:
        columns = [c for c in annual if c.startswith(root)]
        if model.min_training_samples > model.window_days * len(columns):
            raise BacktestError("min_training_samples exceeds available maturity observations")
        jobs.append((root, annual[columns], panel.days_to_expiry[columns], config.min_annual_days, model))
    pieces, stats = process_map(_root_models, jobs, workers=config.workers, work_units=len(annual)*len(annual.columns)*model.window_days,
                               cancel_event=cancel_event, progress=progress, stage="quantile_regression")
    output = pd.concat([p[0] for p in pieces], axis=1).reindex(columns=annual.columns)
    values = {"term_structure_percentile": output}
    for key in pieces[0][1]:
        values[key] = pd.concat([p[1][key] for p in pieces], axis=1).reindex(columns=annual.columns)
    audit = pd.concat([p[2] for p in pieces], ignore_index=True)
    return values, dict(quantile_models=audit), dict(solver="scipy.linprog highs-ds check-loss LP", processes=stats,
        predictors="1 and powers of standardized T/365; separate rolling model per root", target="annual basis in percentage points",
        training="previous complete window_days; no current date; known T below minimum excluded; other missing invalidates fit",
        crossing="sort fitted quantiles per current maturity before conditional-rank interpolation")

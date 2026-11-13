"""Chronological model comparison, probability calibration and paper replay."""
import importlib.util
import warnings
from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import balanced_accuracy_score, brier_score_loss, mean_absolute_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .data import GROUPS, before


@dataclass
class Forecast:
    columns: list
    family: str
    model: object
    calibrator: object
    up_mean: float
    down_mean: float
    error90: float
    threshold: float = .65
    down_given_non_up: float = 1.

    def predict(self, x):
        if self.family == 'zero':
            raw = np.zeros(len(x))
        elif self.family == 'momentum':
            raw = x.r1.to_numpy() * 1e4
        elif self.family == 'logistic':
            raw = self.model.decision_function(x[self.columns])
        else:
            raw = self.model.predict(x[self.columns])
        if self.calibrator is None:
            probability = np.full(len(x), self.up_mean)
        else:
            probability = self.calibrator.predict_proba(raw.reshape(-1, 1))[:, 1]
        expected = raw
        if self.family == 'logistic':
            expected = probability*self.up_mean + (1-probability)*self.down_mean
        return expected, probability


def factories():
    models = {
        'zero': None, 'momentum': None,
        'logistic': lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=300)),
        'ridge': lambda: make_pipeline(StandardScaler(), Ridge(alpha=100)),
    }
    missing = []
    if importlib.util.find_spec('lightgbm'):
        from lightgbm import LGBMRegressor
        models['lightgbm'] = lambda: LGBMRegressor(n_estimators=100, num_leaves=15, max_depth=4,
                                                  random_state=42, verbosity=-1, n_jobs=2)
    else:
        missing.append('lightgbm')
    if importlib.util.find_spec('xgboost'):
        from xgboost import XGBRegressor
        models['xgboost'] = lambda: XGBRegressor(n_estimators=100, max_depth=3, learning_rate=.05,
                                                random_state=42, n_jobs=2, tree_method='hist')
    else:
        missing.append('xgboost')
    return models, missing


def fit(family, factory, columns, training, calibration):
    y = training.target
    model = factory() if factory else None
    if model is not None:
        model.fit(training[columns], (y > 0).astype(int) if family == 'logistic' else y)
    up_mean = float(y[y > 0].mean()) if (y > 0).any() else 0.
    down_mean = float(y[y <= 0].mean()) if (y <= 0).any() else 0.
    forecast = Forecast(columns, family, model, None, up_mean, down_mean, 0.)
    is_up = calibration.target > 0
    forecast.down_given_non_up = float((calibration.target[~is_up] < 0).mean()) if (~is_up).any() else 0.
    if family == 'zero':
        forecast.up_mean = float(is_up.mean())
    else:
        if family == 'logistic':
            scores = model.decision_function(calibration[columns])
        else:
            scores, _ = forecast.predict(calibration)
        if is_up.nunique() != 2:
            raise ValueError('Calibration requires both directional outcomes.')
        forecast.calibrator = LogisticRegression().fit(scores.reshape(-1, 1), is_up)
    predicted, _ = forecast.predict(calibration)
    forecast.error90 = float(np.quantile(np.abs(predicted-calibration.target), .90))
    return forecast


def metrics(actual, expected, up):
    nonflat = actual != 0
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        balanced = balanced_accuracy_score(actual[nonflat] > 0, up[nonflat] >= .5) if nonflat.any() else None
    return {
        'n': len(actual), 'mae_bps': float(mean_absolute_error(actual, expected)),
        'directional_accuracy': float(np.mean((up[nonflat] >= .5) == (actual[nonflat] > 0))) if nonflat.any() else None,
        'balanced_accuracy': balanced,
        'brier': float(brier_score_loss(actual > 0, up)),
    }


def direction(expected, up, spread_bps, commission, slippage, error90=0, threshold=.65):
    hurdle = spread_bps + commission + 2*slippage
    hurdle = np.maximum(hurdle, .25*error90)
    return np.where((expected > hurdle) & (up >= threshold), 1,
                    np.where((expected < -hurdle) & (up <= 1-threshold), -1, 0))


def replay(bars, evaluation, forecast, horizon, point, commission=1., slippage=.5, latency=2):
    """Enter at the first observable bar open after latency, exit at a later open."""
    if min(commission, slippage, latency) < 0:
        raise ValueError('Paper costs and latency must be nonnegative.')
    expected, up = forecast.predict(evaluation)
    trades = []
    available = -np.inf
    times = bars.time.to_numpy()
    prices = bars.open.to_numpy()
    spreads = bars.spread.to_numpy()*point
    signals = direction(expected, up, evaluation.spread_bps, commission, slippage,
                        forecast.error90, forecast.threshold)
    signals[(signals < 0) & ((1-up)*forecast.down_given_non_up < forecast.threshold)] = 0
    for decision, side, volatility in zip(evaluation.time, signals, evaluation.vol60):
        if not side or decision <= available:
            continue
        fill = np.searchsorted(times, decision + latency)
        if fill >= len(times) or times[fill] > decision + latency + 60:
            continue
        exit_at = np.searchsorted(times, times[fill] + horizon*60)
        if exit_at >= len(times) or times[exit_at] > evaluation.time.iloc[-1]:
            continue
        entry = prices[fill] + (spreads[fill] if side > 0 else 0)
        exit_price = prices[exit_at] + (spreads[exit_at] if side < 0 else 0)
        pnl = side*(exit_price-entry)/entry*1e4 - commission - 2*slippage
        trades.append((float(pnl), 'high volatility' if volatility >= .00025 else 'low volatility'))
        available = times[exit_at]
    def summary(values):
        if not values:
            return {'trades': 0}
        pnl = np.asarray(values)
        equity = np.r_[0., pnl.cumsum()]
        losses = -pnl[pnl < 0].sum()
        return {'trades': len(pnl), 'mean_net_bps': float(pnl.mean()), 'win_rate': float((pnl > 0).mean()),
                'max_drawdown_bps': float((np.maximum.accumulate(equity)-equity).max()),
                'profit_factor': float(pnl[pnl > 0].sum()/losses) if losses else None}
    return {**summary([pnl for pnl, _ in trades]),
            'regimes': {regime: summary([pnl for pnl, name in trades if name == regime])
                        for regime in ('high volatility', 'low volatility')}}


def walk_forward(frame, bars, horizon, point, commission=1., slippage=.5, latency=2.):
    """Select using expanding pre-test folds. Fit once and then score the final period."""
    models, missing = factories()
    candidates = [(name, group, factory) for name, factory in models.items()
                  for group in (('price', 'all') if factory else ('price',))]
    if len(frame) < 1000:
        raise ValueError('Need at least 1,000 contiguous labeled examples.')
    final_boundary = frame.time.iloc[int(len(frame)*.8)]
    development = before(frame, final_boundary)
    final = frame[frame.time >= final_boundary]
    results = {}
    fitted = {}
    for name, group, factory in candidates:
        columns = GROUPS['price'] + (GROUPS['context'] if group == 'all' else [])
        folds = []
        for lower, upper in ((.45, .60), (.60, .75), (.75, 1.0)):
            begin = development.time.iloc[int(len(development)*lower)]
            end = development.time.iloc[int(len(development)*upper)] if upper < 1 else final_boundary
            history = before(development, begin)
            split = history.time.iloc[int(len(history)*.8)]
            model = fit(name, factory, columns, before(history, split), history[history.time >= split])
            validation = before(development[development.time >= begin], end)
            expected, up = model.predict(validation)
            folds.append({**metrics(validation.target.to_numpy(), expected, up),
                          'paper': replay(bars, validation, model, horizon, point,
                                          commission, slippage, latency)})
        key = f'{name}/{group}'
        results[key] = {'folds': folds, 'mean_brier': float(np.mean([fold['brier'] for fold in folds]))}
        split = development.time.iloc[int(len(development)*.8)]
        fitted[key] = fit(name, factory, columns, before(development, split),
                          development[development.time >= split])
    winner = min(results, key=lambda key: results[key]['mean_brier'])
    model = fitted[winner]
    expected, up = model.predict(final)
    score = metrics(final.target.to_numpy(), expected, up)
    score['interval_coverage'] = float((np.abs(final.target-expected) <= model.error90).mean())
    paper = replay(bars, final, model, horizon, point, commission, slippage, latency)
    baseline_expected, baseline_up = fitted['zero/price'].predict(final)
    score_baseline = metrics(final.target.to_numpy(), baseline_expected, baseline_up)
    return model, {'winner': winner, 'validation': results, 'final': score, 'naive_final': score_baseline,
                   'final_start_utc_epoch': int(final_boundary), 'missing_models': missing,
                   'paper': paper}

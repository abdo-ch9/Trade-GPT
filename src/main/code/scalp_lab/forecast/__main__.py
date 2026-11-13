"""Train from an immutable local MT5 export, or run the archived latency replay."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import time

import joblib
import numpy as np
import pandas as pd
import sklearn

from .data import HORIZONS, completed, features, labeled
from .research import walk_forward
from .runtime import Engine, SCHEMA, load


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('train', 'benchmark'))
    parser.add_argument('csv', type=Path)
    parser.add_argument('artifact', type=Path)
    parser.add_argument('--broker', choices=('Exness', 'IC Markets'), default='Exness')
    parser.add_argument('--symbol', default='XAUUSDm')
    parser.add_argument('--point', type=float, required=True)
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--commission-bps', type=float, default=1.)
    parser.add_argument('--slippage-bps', type=float, default=.5)
    parser.add_argument('--latency-seconds', type=float, default=2.)
    args = parser.parse_args()
    if not np.isfinite(args.point) or args.point <= 0:
        parser.error('Point must be finite and positive.')
    costs = (args.commission_bps, args.slippage_bps, args.latency_seconds)
    if not all(np.isfinite(value) and value >= 0 for value in costs):
        parser.error('Paper costs and latency must be finite and nonnegative.')
    source = args.csv.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    bars = completed(pd.read_csv(io.BytesIO(source)), time.time(), args.offset)
    if args.command == 'train':
        x = features(bars, args.point)
        artifact = {'schema': SCHEMA, 'broker': args.broker, 'symbol': args.symbol,
                    'point': args.point, 'commission': args.commission_bps, 'slippage': args.slippage_bps,
                    'paper_latency_seconds': args.latency_seconds,
                    'dataset_sha256': digest, 'version': f'forecast-v{SCHEMA}-{digest[:12]}',
                    'libraries': {'numpy': np.__version__, 'pandas': pd.__version__,
                                  'scikit-learn': sklearn.__version__, 'joblib': joblib.__version__},
                    'first_open': int(bars.time.iloc[0]), 'last_open': int(bars.time.iloc[-1]),
                    'bars': len(bars), 'models': {}, 'scores': {}}
        for horizon in HORIZONS:
            artifact['models'][horizon], artifact['scores'][horizon] = walk_forward(
                labeled(bars, x, horizon), bars, horizon, args.point,
                args.commission_bps, args.slippage_bps, args.latency_seconds)
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.artifact.with_suffix('.tmp')
        joblib.dump(artifact, temporary)
        temporary.replace(args.artifact)
        print(json.dumps({k: v for k, v in artifact.items() if k != 'models'}, indent=2))
        return
    artifact = load(args.artifact)
    if artifact['dataset_sha256'] != digest:
        parser.error('Benchmark CSV differs from the training snapshot.')
    engine = Engine(artifact)
    measured = []
    for i in range(max(0, len(bars)-250), len(bars)):
        report = engine.update(lambda count: bars.iloc[i-count+1:i+1], now=bars.time.iloc[i]+60)
        if report['state'] == 'FORECAST':
            measured.append(report)
    fields = ('provider_ms', 'feature_ms', 'inference_ms', 'local_total_ms')
    print(json.dumps({'observations': len(measured), 'p50_p95_ms': {
        field: np.percentile([row[field] for row in measured], [50, 95]).tolist() for field in fields}}, indent=2))


if __name__ == '__main__':
    main()

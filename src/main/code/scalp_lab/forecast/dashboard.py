"""Streamlit view for paper forecasts, isolated from the order workspace."""
from datetime import datetime, timezone

import streamlit as st

from .runtime import Engine, load, mt5_fetch


@st.cache_resource(max_entries=16)
def engine_for(path, modified_ns, identity, offset):
    return Engine(load(path))


@st.fragment(run_every=2)
def live_panel(engine, bridge, identity, symbol, offset):
    try:
        output = engine.update(mt5_fetch(bridge, identity, symbol, engine.artifact['point']), offset=offset)
    except (ValueError, bridge.DemoError) as exc:
        st.warning(str(exc))
        return
    closed = datetime.fromtimestamp(output['close_time'], timezone.utc)
    st.caption(f'{symbol} · completed {closed:%Y-%m-%d %H:%M:%S UTC} · {output["age_seconds"]:.1f}s old')
    st.metric('Last completed close', f'{output["close"]:g}')
    if output['state'] == 'NO SIGNAL':
        st.info(output['reason'])
        return
    generated = datetime.fromtimestamp(output['generated_at'], timezone.utc)
    st.caption(f'{output["version"]} · generated {generated:%H:%M:%S UTC} · '
               f'local processing {output["local_total_ms"]:.2f} ms · MT5 read {output["provider_ms"]:.2f} ms')
    st.dataframe(output['forecasts'], hide_index=True, width='stretch')
    st.caption('Returns and residual uncertainty are in basis points. Down and flat split the calibrated non-up probability using calibration-period frequencies.')


def render(bridge, directory, offset):
    st.header('XAU/USD paper forecasts')
    st.caption('Market observations feed simulated signals. This workspace does not submit orders.')
    artifacts = sorted(directory.glob('forecast-*.joblib'))
    if not artifacts:
        st.info('Train a local forecast artifact using the instructions in README.')
        return
    path = st.selectbox('Local forecast artifact', artifacts, format_func=lambda item: item.stem)
    if st.button('Connect MT5 for forecasts'):
        try:
            if bridge.BROKER_NAME == 'Exness':
                st.session_state.forecast_identity = bridge.connect(read_only=True)
            else:
                st.session_state.forecast_identity = bridge.connect()
        except bridge.DemoError as exc:
            st.warning(str(exc))
    identity = st.session_state.get('forecast_identity')
    try:
        engine = engine_for(path, path.stat().st_mtime_ns, identity, offset)
    except (OSError, ValueError) as exc:
        st.warning(str(exc))
        return
    artifact = engine.artifact
    if artifact['broker'] != bridge.BROKER_NAME:
        st.warning('The artifact was trained for a different broker.')
        return
    if identity:
        live_panel(engine, bridge, identity, artifact['symbol'], offset)
    with st.expander('Historical walk-forward evaluation and paper replay'):
        scores = artifact['scores']
        st.dataframe([{'Horizon (min)': horizon, 'Model': score['winner'], **score['final'],
                       'Paper trades': score['paper']['trades']} for horizon, score in scores.items()],
                     hide_index=True, width='stretch')
        st.json(scores, expanded=False)

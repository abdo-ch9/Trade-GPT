"""Local background gold scanner and independent one-second exit watchdog."""
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from . import auto_demo as auto, mt5_demo as bridge
from .gold_events import record
from .gold_exits import manage,EXIT_POLICY
from .gold_storage import write_json

ROOT=Path(__file__).resolve().parents[1]
HEARTBEAT=ROOT/'gold_worker_status.json'


def status():
    try:
        return json.loads(HEARTBEAT.read_text())
    except (OSError,ValueError):
        return {}


def healthy(state=None,now=None):
    state=status() if state is None else state
    now=time.time() if now is None else now
    return (state.get('exit_policy')==EXIT_POLICY and not state.get('exit_error')
            and 0<=now-state.get('heartbeat',0)<15
            and 0<=now-state.get('last_exit_check',0)<15)


def ensure_running():
    state=status()
    if 0<=time.time()-state.get('heartbeat',0)<15:
        return
    with open(ROOT/'gold_worker.log','a',encoding='utf-8') as log:
        subprocess.Popen([sys.executable,'-m','scalp_lab.gold_worker'],cwd=ROOT,
            stdout=log,stderr=log,stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


def reconnect(identity):
    """Recover a lost worker connection, then verify the originally armed account."""
    with bridge.LOCK:
        mt5 = bridge.api()
        terminal = mt5.terminal_info()
        if terminal is None or not terminal.connected or mt5.account_info() is None:
            if not mt5.initialize(timeout=10000):
                raise bridge.DemoError('Background worker cannot reconnect to MT5. Keep the demo terminal open and connected.')
        bridge.checked_account(mt5, identity)


def initialize_worker(mt5):
    """Bounded recovery when the terminal is still starting; no orders are sent."""
    for attempt in range(3):
        if mt5.initialize(timeout=10000):
            return True
        if attempt < 2:
            time.sleep(2)
    return False


def run():
    import msvcrt
    try:
        lock=open(ROOT/'gold_worker.lock','a+b')
    except OSError:
        return
    try:
        lock.seek(0, 2)
        if lock.tell() == 0:
            try:
                lock.write(b'0'); lock.flush()
            except OSError:
                pass
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            lock.close()
            return
    except OSError:
        lock.close()
        return
    state={'pid':os.getpid(),'started':time.time(),'scanner':'idle','exit_policy':EXIT_POLICY}
    gate=threading.Lock()
    def scan_loop():
        while True:
            try:
                config=auto.settings()
                if config.get('enabled') and config.get('identity'):
                    with gate:
                        state['scanner']='analyzing'
                        state['scan_started']=time.time()
                    reconnect(config['identity'])

                    auto.scan(config['identity'],config['offset'])
                    with gate:
                        state['last_scan']=time.time()
                        state['scanner']='waiting for next scan'
                else:
                    with gate:
                        state['scanner']='entries stopped; exits monitored'
            except bridge.DemoError as exc:
                record('blocked',str(exc),key=f'worker:{exc}:{int(time.time()//300)}')
                with gate:
                    state['scanner']=str(exc)
            except Exception as exc:
                try:
                    auto.stop('Worker scan error; inspect event history.')
                finally:
                    record('error',str(exc),{'traceback':traceback.format_exc()})
            time.sleep(5)
    mt5=bridge.api()
    if not initialize_worker(mt5):
        record('error','Cannot initialize MT5 for background gold worker.')
        return
    scanner=threading.Thread(target=scan_loop,daemon=True)
    scanner.start()
    from .telegram_notifications import start as start_telegram
    start_telegram()
    record('worker','Gold worker started; 15-minute exit watchdog active.')
    while True:
        config=auto.settings()
        error=None
        try:
            if config.get('identity'):
                with auto.process_guard(),bridge.LOCK:
                    reconnect(config['identity'])

                    manage(config['identity'],auto.JOURNAL)
                with gate:
                    state['last_exit_check']=time.time()
        except bridge.DemoError as exc:
            error=str(exc)
            if 'Another automation scan' not in error:
                record('exit_delayed',error,key=f'watchdog:{error}:{int(time.time()//300)}')
        except Exception as exc:
            error=str(exc)
            auto.stop('Exit watchdog error; inspect event history.')
            record('error',error,{'traceback':traceback.format_exc()},key=f'exit-worker:{error}:{int(time.time()//300)}')
        with gate:
            state.update(heartbeat=time.time(),entries_enabled=config.get('enabled',False),
                         scanner_alive=scanner.is_alive(),exit_error=error)
            snapshot=dict(state)
        try:
            write_json(HEARTBEAT,snapshot)
        except OSError as exc:
            # Keep protecting existing positions. An expired persisted heartbeat blocks entries.
            record('error','Could not publish worker heartbeat: '+str(exc),
                   key=f'heartbeat-write:{int(time.time()//300)}')
        time.sleep(1)


if __name__=='__main__':
    run()

"""Optional Telegram decision notifications, isolated from order execution."""
import hashlib
import json
import os
import threading
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import requests
from dotenv import dotenv_values

from .gold_events import DB
from .gold_storage import write_json

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'telegram_notifications.json'


def configuration():
    local = dotenv_values(ROOT / '.env')
    return {name: (os.getenv(name) or local.get(name) or '').strip()
            for name in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID')}


def send_message(config, text):
    # Never log the request URL or exceptions: the URL contains the bot secret.
    try:
        response = requests.post(
            'https://api.telegram.org/bot'+config['TELEGRAM_BOT_TOKEN']+'/sendMessage',
            json={'chat_id': config['TELEGRAM_CHAT_ID'], 'text': text[:4000],
                  'link_preview_options': {'is_disabled': True}},
            timeout=(3, 8), allow_redirects=False)
        return response.status_code == 200 and response.json().get('ok') is True
    except (requests.RequestException, ValueError):
        return False


def poll_once(db_path=DB, state_path=STATE):
    config = configuration()
    if not all(config.values()) or not Path(db_path).exists():
        return
    try:
        state = json.loads(Path(state_path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        state = None
    with closing(sqlite3.connect(db_path, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='events'").fetchone():
            return
        if state is None:
            # Start with future events; never send a backlog on first activation.
            last = db.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
            write_json(state_path, {'cursor': last, 'signatures': {}, 'status': 'Waiting for new decisions'})
            return
        rows = db.execute('SELECT * FROM events WHERE id>? ORDER BY id LIMIT 100', (state.get('cursor', 0),)).fetchall()
    signatures = state.setdefault('signatures', {})
    for row in rows:
        if row['kind'] == 'decision' and time.time()-row['time'] < 300:
            detail = json.loads(row['details'])
            symbol = detail.get('symbol') or row['message'].split(':', 1)[0]
            signature = hashlib.sha256(json.dumps([
                detail.get('action', row['message']), detail.get('direction'), detail.get('setup'),
                detail.get('reasons', [])], sort_keys=True).encode()).hexdigest()
            if signatures.get(symbol) != signature:
                stamp = datetime.fromtimestamp(row['time'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                text = f"Gold demo decision · {symbol}\n{stamp}\n{detail.get('action', row['message'])}\nSetup: {detail.get('setup', 'Unavailable')}"
                for key, label in [('direction', 'Chart direction'), ('entry', 'Indicative entry'), ('sl', 'Stop loss'), ('tp', 'Take profit')]:
                    if detail.get(key) is not None:
                        text += f'\n{label}: {detail[key]}'
                text += '\n'+'\n'.join(detail.get('reasons', []))
                text += '\nDecision notification; not confirmation of a broker fill.'
                if not send_message(config, text):
                    state.update(status='Telegram delivery failed; check bot, chat ID and connection', last_attempt=time.time())
                    write_json(state_path, state)
                    return
                signatures[symbol] = signature
                state.update(status='Delivered', last_sent=time.time())
        state['cursor'] = row['id']
        write_json(state_path, state)


def run():
    while True:
        try:
            poll_once()
        except Exception:
            # Notification failures must never interrupt scanning or timed exits.
            pass
        time.sleep(5)


def start():
    threading.Thread(target=run, daemon=True, name='telegram-notifications').start()

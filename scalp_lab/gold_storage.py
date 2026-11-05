"""Atomic JSON updates, including short Windows sharing-lock retries."""
import json
import os
import time
import uuid
from pathlib import Path


def write_json(path,value):
    path=Path(path)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('w',encoding='utf-8') as handle:
            json.dump(value,handle,indent=2,default=str)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(6):
            try:
                temp.replace(path)
                return
            except PermissionError:
                if attempt==5:
                    raise
                time.sleep(.05*(attempt+1))
    finally:
        temp.unlink(missing_ok=True)

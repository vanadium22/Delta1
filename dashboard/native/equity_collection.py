"""Slow equity snapshots owned by the main collector's network lease.

Separate HTTP session and storage keep constituent batches off the two-second
headline path. No VPN control, Wind access, or historical bar publication.
"""
from datetime import datetime, timezone
from pathlib import Path
import threading
import time
import uuid

from dashboard.marketdata.bars import _atomic_bytes, _json_bytes
from dashboard.marketdata.overview_reference import load
from dashboard.marketdata.overview_contributions import equity_path
from index_strategy.instant_dld.realtime_store import RealtimeStore


class EquitySampler:
    def __init__(self, local_root, config, policy, client_factory):
        self.local_root = Path(local_root)
        self.config = config
        self.policy = policy
        self.client_factory = client_factory
        self.stop_event = threading.Event()
        self.worker = None
        self.status = {'status': 'waiting_reference'}

    def running(self):
        return self.worker is not None and self.worker.is_alive()

    def stop(self):
        self.stop_event.set()

    def cycle(self, client, store, reference, poll):
        members = {r['symbol'] for g in reference['data'].get('indices', {}).values() for r in g.get('rows', [])}
        indices = {g['index_id'] for g in reference['data'].get('indices', {}).values() if g.get('rows')}
        symbols = sorted(members | indices)
        if not symbols:
            return None
        started = datetime.now(timezone.utc).isoformat()
        quotes = {}; failed = []
        size = 100
        for offset in range(0, len(symbols), size):
            if self.stop_event.is_set() or not self.policy()['allowed']:
                return None
            batch = symbols[offset:offset+size]
            result = client.fetch(batch)
            result.update(symbols=batch, poll=poll, batch=offset//size+1,
                          batch_count=(len(symbols)+size-1)//size)
            # The existing store preserves original HTTP bodies before parsing.
            store.batch(result)
            for row in store.last_rows:
                quotes[row['symbol']] = dict(row, observed_at=row['received_at'])
            failed.extend(result.get('missing_symbols', []))
        if self.stop_event.is_set():
            return None
        value = dict(schema='overview-equities-v1', snapshot_id=uuid.uuid4().hex,
            reference_version=reference['version'], started_at=started,
            finished_at=datetime.now(timezone.utc).isoformat(), quotes=quotes,
            requested_count=len(symbols), failed_symbols=failed)
        _atomic_bytes(equity_path(self.config, self.local_root), _json_bytes(value))
        self.status = dict(status='sampled', snapshot_at=value['finished_at'], rows=len(quotes), requested=len(symbols))
        return value

    def start(self):
        def work():
            client = store = None; poll = 0
            try:
                while not self.stop_event.is_set() and self.policy()['allowed']:
                    started = time.monotonic()
                    reference = load(self.config, self.local_root)
                    if any(g.get('rows') for g in reference['data'].get('indices', {}).values()):
                        if client is None:
                            client = self.client_factory(connect_timeout=5, read_timeout=10)
                            store = RealtimeStore(self.local_root/'overview_equities/observations')
                        poll += 1
                        self.cycle(client, store, reference, poll)
                    self.stop_event.wait(max(1, 60-(time.monotonic()-started)))
            except Exception as exc:
                self.status = dict(status='failed', error_type=type(exc).__name__)
            finally:
                if store is not None:
                    store.close()
                if client is not None:
                    client.close()
        self.worker = threading.Thread(target=work, name='overview-minute-equities', daemon=True)
        self.worker.start()

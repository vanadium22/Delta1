"""Rolling equity snapshots owned by the main collector's network lease.

Separate HTTP session and storage keep constituent batches off the three-second
headline path. No VPN control, Wind access, or historical bar publication.
"""
from datetime import datetime, timezone
from pathlib import Path
import threading
import time
import uuid

from dashboard.marketdata.bars import _atomic_bytes, _json_bytes
from dashboard.marketdata.overview_reference import load
from dashboard.marketdata.overview_contributions import equity_path,read_equities
from dashboard.marketdata.overview_reference import finite
from dashboard.marketdata.equity_observations import EquityObservationStore


class EquitySampler:
    def __init__(self, local_root, config, policy, client_factory, *, pause=None):
        self.local_root = Path(local_root)
        self.config = config
        self.policy = policy
        self.client_factory = client_factory
        self.stop_event = threading.Event()
        self.pause=pause or self.stop_event.wait
        self.worker = None
        self.status = {'status': 'waiting_reference'}
        self.archive = {}
        try:self.batch_size=max(100,min(500,int(config.get('overview_equity_batch_size',300))))
        except (ValueError,TypeError):self.batch_size=300

    def state(self):
        return dict(self.status, worker_running=self.running(), archive=dict(self.archive))

    def archive_progress(self, value):
        self.archive = value

    def running(self):
        return self.worker is not None and self.worker.is_alive()

    def stop(self):
        self.stop_event.set()

    def cycle(self, client, store, reference, poll):
        members={r['symbol'] for g in reference['data'].get('indices',{}).values() for r in g.get('rows',[])}
        indices={g['index_id'] for g in reference['data'].get('indices',{}).values() if g.get('rows')}
        if not members and not indices:return None
        started=datetime.now(timezone.utc).isoformat();value=None
        prior=read_equities(self.config,self.local_root)
        quotes={s:q for s,q in prior.get('quotes',{}).items() if s in members|indices}
        failed=set(prior.get('failed_symbols',[])) & (members|indices)
        def priority(symbol):
            q=quotes.get(symbol,{})
            return (0 if symbol in failed else 1 if symbol not in quotes else 2,str(q.get('source_event_time') or ''),symbol)
        symbols=sorted(indices)+sorted(members-indices,key=priority)
        size=self.batch_size;interval=15.;batches=(len(symbols)+size-1)//size
        for offset in range(0,len(symbols),size):
            if self.stop_event.is_set() or not self.policy()['allowed']:return value
            batch=symbols[offset:offset+size];number=offset//size+1
            self.status=dict(status='requesting',batch=number,batch_count=batches,rows=len(quotes),requested=len(symbols))
            try:result=client.fetch(batch)
            except Exception as exc:
                result=dict(status='request_failed',received_at=datetime.now(timezone.utc).isoformat(),
                    response={},missing_symbols=batch,error_type=type(exc).__name__)
            result.update(symbols=batch,poll=poll,batch=number,batch_count=batches)
            store.batch(result)
            received=set()
            for row in store.last_rows:
                if not finite(row.get('close')) or row['close']<=0 or not row.get('source_event_time'):continue
                old=quotes.get(row['symbol'],{})
                try:
                    incoming=datetime.fromisoformat(row['source_event_time'])
                    previous=datetime.fromisoformat(old['source_event_time']) if old.get('source_event_time') else None
                    if previous is not None and incoming<previous:continue
                except (ValueError,TypeError):continue
                compact={k:row.get(k) for k in ('symbol','close','prev_close','source_event_time','received_at','source_date_basis','snapshot_status','sequence')}
                compact['observed_at']=row['received_at']
                if (not finite(compact.get('prev_close')) or compact['prev_close']<=0) and previous is not None and incoming.date()==previous.date() and finite(old.get('prev_close')) and old['prev_close']>0:
                    compact.update(prev_close=old['prev_close'],prev_close_source='saved_same_day_http')
                quotes[row['symbol']]=compact;failed.discard(row['symbol']);received.add(row['symbol'])
            failed.update(set(batch)-received)
            failed.update(result.get('missing_symbols',[]));failed.update(result.get('failed_symbols',[]))
            # A server may cap large responses. Retry missing codes next round
            # using smaller batches, without a tight retry loop or faster cadence.
            if len(batch)>=200 and len(received)<len(batch)*.7:self.batch_size=100
            value=dict(schema='overview-equities-v1',mode='rolling',snapshot_id=uuid.uuid4().hex,
                reference_version=reference['version'],started_at=started,finished_at=datetime.now(timezone.utc).isoformat(),
                quotes=quotes,requested_count=len(symbols),failed_symbols=sorted(failed),batch=number,batch_count=batches,
                round_complete=number==batches,batch_size=size,next_batch_size=self.batch_size,pending_count=len(failed),
                batch_interval_seconds=interval,round_target_seconds=max(300,batches*interval),quote_max_age_seconds=360)
            _atomic_bytes(equity_path(self.config,self.local_root),_json_bytes(value))
            self.status=dict(status='sampled' if number==batches else 'sampling',snapshot_at=value['finished_at'],rows=len(quotes),
                requested=len(symbols),batch=number,batch_count=batches,batch_size=size,next_batch_size=self.batch_size,pending_count=len(failed),
                batch_interval_seconds=interval,round_target_seconds=max(300,batches*interval))
            if number<batches and self.pause(interval):return value
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
                            client = self.client_factory(connect_timeout=1, read_timeout=2)
                            store = EquityObservationStore(self.local_root/'overview_equities/observations', progress=self.archive_progress,archive_enabled=False)
                        poll += 1
                        self.cycle(client, store, reference, poll)
                    self.stop_event.wait(max(1, 300-(time.monotonic()-started)))
            except Exception as exc:
                self.status = dict(status='failed', error_type=type(exc).__name__)
            finally:
                failed = self.status.get('status') == 'failed'
                self.status = dict(self.status, status='draining')
                try:
                    if store is not None:
                        store.close()
                except Exception as exc:
                    self.status = dict(self.status, status='failed', error_type=type(exc).__name__)
                finally:
                    if client is not None:
                        try:
                            client.close()
                        except Exception as exc:
                            self.status = dict(self.status, status='failed', error_type=type(exc).__name__)
                if failed:
                    self.status = dict(self.status, status='failed')
                elif self.status.get('status') != 'failed':
                    self.status = dict(self.status, status='stopped')
        self.worker = threading.Thread(target=work, name='overview-minute-equities', daemon=True)
        self.worker.start()

"""App constituent archives, with bounded file writers and batched catalog commits.

The existing SQLite/raw/Parquet formats and reader stay unchanged. Each file is
immutable and durable before its catalog entry commits. Closing drains every
owned writer; interrupted catalogs can replay from the already committed quotes.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import time

from index_strategy.instant_dld.realtime_store import RealtimeStore, publish_parquet


class EquityObservationStore(RealtimeStore):
    def __init__(self, root, *, progress=lambda value: None):
        self.progress = progress
        super().__init__(root)

    def flush_parquet(self):
        started = time.monotonic()
        groups = self.connection.execute("""SELECT q.symbol,q.capture_date,q.newest,COALESCE(p.archived,0) AS archived
            FROM (SELECT symbol,capture_date,MAX(sequence) AS newest FROM quotes GROUP BY symbol,capture_date) q
            LEFT JOIN (SELECT symbol,capture_date,MAX(last_sequence) AS archived FROM parquet_parts
                       GROUP BY symbol,capture_date) p
            ON q.symbol=p.symbol AND q.capture_date=p.capture_date
            WHERE q.newest>COALESCE(p.archived,0)""").fetchall()
        pending = deque()
        catalog = []
        finished = set()
        parts = rows = 0

        def report(status, **extra):
            self.progress(dict(status=status, symbols_total=len(groups), symbols_finished=len(finished),
                parts_published=parts, rows_published=rows, elapsed_seconds=round(time.monotonic()-started, 3),
                updated_at=datetime.now(timezone.utc).isoformat(), **extra))

        def write(records, directory, day):
            return publish_parquet(self._archive_table(records), directory, day)

        def commit():
            nonlocal parts, rows
            if not catalog:
                return
            with self.connection:
                self.connection.executemany('INSERT INTO parquet_parts VALUES (?,?,?,?,?,?)', [row for row, _ in catalog])
            for row, complete in catalog:
                parts += 1
                rows += row[-1]
                if complete:
                    finished.add((row[1], row[2]))
            catalog.clear()
            report('archiving')

        def accept():
            group, records, future = pending.popleft()
            target = future.result()
            row = (target.relative_to(self.root).as_posix(), group['symbol'], group['capture_date'],
                records[0]['sequence'], records[-1]['sequence'], len(records))
            catalog.append((row, records[-1]['sequence'] >= group['newest']))
            if len(catalog) >= 64:
                commit()

        report('archiving')
        try:
            # At most four parts are held or written concurrently. SQLite stays
            # on its owner thread; all file writers finish before releasing it.
            with ThreadPoolExecutor(max_workers=4, thread_name_prefix='equity-archive') as pool:
                for group in groups:
                    after = group['archived']
                    while True:
                        records = self.connection.execute("""SELECT * FROM quotes WHERE symbol=? AND capture_date=?
                            AND sequence>? ORDER BY sequence LIMIT 50000""",
                            (group['symbol'], group['capture_date'], after)).fetchall()
                        if not records:
                            break
                        day = group['capture_date']
                        directory = self.root/'data'/group['symbol']/day[:4]/day[5:7]
                        pending.append((group, records, pool.submit(write, records, directory, day)))
                        after = records[-1]['sequence']
                        if len(pending) >= 4:
                            accept()
                while pending:
                    accept()
                commit()
            report('complete')
        except BaseException as exc:
            report('failed', error_type=type(exc).__name__)
            raise

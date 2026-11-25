"""Short-lived quote subscriptions sent to the Dashboard collector by local Apps."""
from datetime import datetime
import json
from pathlib import Path
import re
from uuid import uuid4

from shared_data.io import atomic_json


TTL_SECONDS = 18
KEEPALIVE_SECONDS = 6
MAX_CODES = 100
CASH = re.compile(r'[0-9]{6}\.(?:SH|SZ)')
FUTURES = re.compile(r'(?:IF|IH|IC|IM)[0-9]{2}(?:0[1-9]|1[0-2])\.CFE')
CLIENT_FILE = re.compile(r'[a-f0-9]{32}\.json')


def supported(code):
    return isinstance(code, str) and (CASH.fullmatch(code) or FUTURES.fullmatch(code)) is not None


def directory(root):
    return Path(root) / 'live' / 'consumer_quotes'


def requested_codes(root, at):
    try:
        paths = list(directory(root).glob('*.json'))
    except OSError:
        return []
    records = []
    for path in paths:
        if not CLIENT_FILE.fullmatch(path.name) or path.is_symlink():
            continue
        try:
            with path.open(encoding='utf-8') as stream:
                payload = json.loads(stream.read(8192))
            if not isinstance(payload, dict):
                continue
            created = datetime.fromisoformat(payload['published_at'])
            codes = payload['codes']
            if not -2 <= (at - created).total_seconds() <= TTL_SECONDS or not isinstance(codes, list):
                continue
        except (OSError, KeyError, TypeError, ValueError):
            continue
        records.append((created, [s for s in codes[:MAX_CODES] if supported(s)]))
    # Recently requested codes are preferred when Dashboard's request reaches capacity.
    return list(dict.fromkeys(s for _, codes in sorted(records, key=lambda entry: entry[0], reverse=True) for s in codes))


class QuoteSubscription:
    def __init__(self):
        self.filename = f'{uuid4().hex}.json'
        self.path = None
        self.codes = ()
        self.published = None

    def publish(self, root, codes, at):
        path = directory(root) / self.filename
        codes = tuple(dict.fromkeys(code for code in codes if supported(code)))[:MAX_CODES]
        if not codes:
            self.close()
            return False
        if self.path and path != self.path:
            self.close()
        if self.published and self.codes == codes and 0 <= (at - self.published).total_seconds() < KEEPALIVE_SECONDS:
            return True
        try:
            atomic_json(path, {'published_at': at.isoformat(), 'codes': list(codes)})
        except OSError:
            return False
        self.path, self.codes, self.published = path, codes, at
        return True

    def close(self):
        if self.path:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass  # Abandoned requests expire independently of the owning process.
        self.path, self.codes, self.published = None, (), None

"""Only synthetic failures for the opt-in native startup protocol check."""
import argparse
import errno
from pathlib import Path
import sys
from unittest.mock import patch
from dashboard.numeric_snapshot import save_snapshot
from dashboard import numeric_startup as startup

parser=argparse.ArgumentParser()
parser.add_argument('action')
parser.add_argument('--local-root',type=Path)
parser.add_argument('--report',type=Path)
parser.add_argument('--stop-file',type=Path)
args=parser.parse_args()
if args.action=='stale':
    save_snapshot(dict(state='complete',ok=True,message='old synthetic result'),args.report)
    raise SystemExit(1)
if args.action=='missing':
    print('Synthetic worker failed before JSON report',file=sys.stderr)
    raise SystemExit(1)
error=PermissionError(errno.EACCES,'fixture-secret-password',str(args.local_root/'fixture.locked.json'))
gate=dict(allowed=True,reason='synthetic session',checked_at='2026-10-22T14:32:57+08:00')
with patch.object(startup,'summary',side_effect=error), \
     patch('dashboard.session_clock.session_policy',return_value=gate):
    raise SystemExit(startup.main(['summary','--local-root',str(args.local_root),'--report',str(args.report)]))

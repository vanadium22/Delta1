"""Synthetic cancellable worker for the Windows startup lifecycle test; no network."""
import argparse
import os
from pathlib import Path
import time
from dashboard.numeric_snapshot import save_snapshot

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action')
    parser.add_argument('--report',type=Path)
    parser.add_argument('--stop-file',type=Path)
    parser.add_argument('--local-root')
    args=parser.parse_args()
    deadline=time.monotonic()+10
    while not args.stop_file.exists() and time.monotonic()<deadline:
        time.sleep(.05)
    save_snapshot(dict(state='synthetic_stopped',pid=os.getpid(),cancelled=args.stop_file.exists()),args.report)

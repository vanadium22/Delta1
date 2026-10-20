"""Synthetic child-lifetime fixture. Never reads credentials or opens a network."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--record', type=Path, required=True)
    args = parser.parse_args()
    if args.child:
        if sys.stdin.readline().strip() != 'ready':
            return
        args.record.write_text(json.dumps(dict(child=os.getpid())), encoding='utf8')
        time.sleep(120)
    else:
        from dashboard.marketdata.ddb_vpn import child_lifetime
        process = subprocess.Popen([sys.executable,'-B','-m','tests.numeric_vpn_worker','--child',
            '--record',str(args.record)], stdin=subprocess.PIPE,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        with child_lifetime(process):
            process.stdin.write(b'ready\n')
            process.stdin.close()
            time.sleep(120)


if __name__ == '__main__':
    main()

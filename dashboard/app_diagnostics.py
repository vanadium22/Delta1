"""Bounded observation of running Apps, without network requests or process control."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=int,default=15)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not 1<=args.seconds<=900:parser.error('--seconds must be between 1 and 900')
    root=Path(__file__).parent/'runtime/app_sessions';samples=[];deadline=time.monotonic()+args.seconds
    while True:
        now=datetime.now(timezone.utc);runs=[]
        for path in root.glob('*/status.json'):
            try:
                value=json.loads(path.read_text(encoding='utf8'))
                if (now-datetime.fromisoformat(value['observed_at'])).total_seconds()<60:runs.append(value)
            except (OSError,ValueError,KeyError):continue
        samples.append(dict(observed_at=now.isoformat(),runs=runs))
        left=deadline-time.monotonic()
        if left<=0:break
        time.sleep(min(3,left))
    report=dict(schema='app-observation-v1',seconds=args.seconds,samples=samples,
                network_requested=False,vpn_changed=False,company_acceptance='pending_user_observation')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(str(args.output.resolve()));return 0

if __name__=='__main__':raise SystemExit(main())

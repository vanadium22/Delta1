"""Offline dependency/profile checks. Never opens windows or starts maintenance."""
import argparse
import importlib
import importlib.metadata
import json
from pathlib import Path
import sys


def check(local_root=None):
    from .native.bootstrap import configure_qt
    configure_qt()
    checks={}
    for name in ('pandas','numpy','pyarrow','requests','openpyxl','PySide6.QtWidgets','pyqtgraph'):
        try:module=importlib.import_module(name);checks[name]=dict(ok=True,version=getattr(module,'__version__',None))
        except Exception as exc:checks[name]=dict(ok=False,error_type=type(exc).__name__)
    from .app_config import prepare_config,credential_state,history_python
    from .marketdata.history_quick import quick_check
    # Inspection does not create the App configuration copy.
    base=Path(__file__).parent/'localsetting'
    selected=Path(local_root)/'native.json' if local_root is not None else next((p for p in (base/'app/native.json',base/'numeric_excel/native.json',base/'native.json') if p.is_file()),None)
    profile_error=None
    try:config=json.loads(selected.read_text(encoding='utf-8-sig')) if selected and selected.is_file() else {}
    except (OSError,ValueError) as exc:config={};profile_error=type(exc).__name__
    try:quick=quick_check(config)
    except Exception as exc:quick=dict(error_type=type(exc).__name__,message='历史快检失败；主窗口内查看配置与诊断')
    return dict(python=sys.executable,checks=checks,profile=str(selected) if selected else None,
                profile_error=profile_error,credentials=credential_state(config,selected.parent if selected else None),history_python=history_python(config),quick=quick,
                ok=profile_error is None and all(v['ok'] for v in checks.values()),vpn_changed=False,network_requested=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);parser.add_argument('--local-root',type=Path);args=parser.parse_args()
    try:report=check(args.local_root)
    except Exception as exc:report=dict(ok=False,stage='preflight',error_type=type(exc).__name__,python=sys.executable)
    raw=json.dumps(report,ensure_ascii=False,indent=2)
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(raw,encoding='utf8')
    print(raw);return 0 if report['ok'] else 1

if __name__=='__main__':raise SystemExit(main())

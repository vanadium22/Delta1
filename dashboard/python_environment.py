"""Check and prepare a selected Python without changing its site-packages."""
import argparse
import hashlib
import importlib
import importlib.util
try:import importlib.metadata as metadata
except ImportError:metadata=None
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
MODULES={'PySide6-Essentials':'PySide6.QtWidgets','shiboken6':'shiboken6',
         'pyqtgraph':'pyqtgraph','colorama':'colorama','pandas':'pandas','numpy':'numpy',
         'pyarrow':'pyarrow','requests':'requests','openpyxl':'openpyxl','dolphindb':'dolphindb'}


def identity(executable=None,*,root=ROOT,version=None,bits=None):
    executable=os.path.normcase(os.path.abspath(str(executable or sys.executable)))
    bundled=os.path.normcase(os.path.abspath(str(Path(root)/'runtime'/'python'/'python.exe')))
    if executable==bundled:executable='bundled-runtime'
    version=version or f'{sys.version_info.major}.{sys.version_info.minor}'
    bits=bits or struct.calcsize('P')*8
    return 'py'+str(version).replace('.','')+'-'+str(bits)+'-'+hashlib.sha256(executable.encode('utf8')).hexdigest()[:12]


def overlay_root(root=ROOT,executable=None):return Path(root)/'.deps'/'python'/identity(executable,root=root)


def active_overlay(root=ROOT,executable=None):
    base=overlay_root(root,executable)
    try:
        pointer=json.loads((base/'current.json').read_text(encoding='utf8'))
        generation=pointer['generation']
        if not re.fullmatch(r'[a-f0-9]{32}',generation):return None
        path=base/generation
        return path if path.is_dir() else None
    except (OSError,ValueError,TypeError,KeyError):return None


def child_environment(executable,environ=None):
    """Do not inject this interpreter's binary packages into another Python."""
    env=dict(os.environ if environ is None else environ)
    parent=env.get('DELTA1_APP_PYTHON');overlay=env.get('DELTA1_APP_OVERLAY')
    if parent and overlay and os.path.normcase(os.path.abspath(str(executable)))!=os.path.normcase(os.path.abspath(parent)):
        paths=env.get('PYTHONPATH','').split(os.pathsep)
        paths=[p for p in paths if os.path.normcase(os.path.abspath(p))!=os.path.normcase(os.path.abspath(overlay))]
        if paths:env['PYTHONPATH']=os.pathsep.join(paths)
        else:env.pop('PYTHONPATH',None)
        env.pop('DELTA1_APP_PYTHON',None);env.pop('DELTA1_APP_OVERLAY',None)
    return env


def requirements(path=None):
    root=(Path(path) if path else ROOT/'dashboard'/'requirements-app.txt').resolve()
    def read(file,seen):
        if file in seen:raise ValueError('recursive_requirements')
        seen.add(file);items=[]
        for line in file.read_text(encoding='utf8').splitlines():
            line=line.strip()
            if not line or line.startswith('#'):continue
            if line.startswith('-r '):items.extend(read((file.parent/line[3:].strip()).resolve(),seen));continue
            match=re.fullmatch(r'([A-Za-z0-9_.-]+)(.*)',line)
            if not match or match[1] not in MODULES:raise ValueError('unsupported_requirement')
            items.append((match[1],match[2]))
        return items
    return read(root,set())


def version_matches(version,spec):
    try:
        try:from packaging.version import Version
        except ImportError:
            try:from pip._vendor.packaging.version import Version
            except ImportError:
                def Version(value):
                    match=re.fullmatch(r'\s*(\d+(?:\.\d+)*)(?:\+[A-Za-z0-9.]+)?\s*',value)
                    if not match:raise ValueError('unknown_version')
                    parts=tuple(int(p) for p in match[1].split('.'))
                    return (parts+(0,)*8)[:8]
        actual=Version(version)
        for part in filter(None,(p.strip() for p in spec.split(','))):
            match=re.fullmatch(r'(==|>=|<=|>|<)([A-Za-z0-9_.+-]+)',part)
            if not match:return False
            target=Version(match[2]);op=match[1]
            if not {'==':actual==target,'>=':actual>=target,'<=':actual<=target,'>':actual>target,'<':actual<target}[op]:return False
        return True
    except (ImportError,ValueError,TypeError):return False


def probe(*,root=ROOT,candidate=None):
    overlay=Path(candidate) if candidate else active_overlay(root)
    compatible=sys.version_info>=(3,10) and struct.calcsize('P')*8==64
    if not compatible:
        return dict(schema='dashboard-python-check-v1',python=sys.executable,version=sys.version.split()[0],
            bits=struct.calcsize('P')*8,compatible=False,overlay=str(overlay) if overlay else None,
            packages=[],windpy_detected=False,ok=False,stage='unsupported_python')
    legacy=Path(root)/'.deps'/'dashboard_native'
    for path in (legacy,overlay):
        if path and path.is_dir():sys.path.insert(0,str(path))
    items=[]
    for name,spec in requirements(Path(root)/'dashboard'/'requirements-app.txt'):
        try:
            importlib.import_module(MODULES[name])
            try:version=metadata.version(name).strip()
            except metadata.PackageNotFoundError:
                version=str(getattr(importlib.import_module(MODULES[name].split('.')[0]),'__version__','')).strip()
            valid=version_matches(version,spec)
            items.append(dict(package=name,requirement=spec,version=version,status='ok' if valid else 'version_mismatch'))
        except Exception as exc:
            items.append(dict(package=name,requirement=spec,version=None,status='missing_or_broken',error_type=type(exc).__name__))
    try:wind=importlib.util.find_spec('WindPy') is not None
    except (ImportError,ValueError,AttributeError):wind=False
    return dict(schema='dashboard-python-check-v1',python=sys.executable,version=sys.version.split()[0],
        bits=struct.calcsize('P')*8,compatible=compatible,overlay=str(overlay) if overlay else None,
        packages=items,windpy_detected=wind,ok=compatible and all(v['status']=='ok' for v in items))


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('x',encoding='utf8') as handle:
            json.dump(value,handle,ensure_ascii=False,indent=2);handle.flush();os.fsync(handle.fileno())
        os.replace(tmp,path)
    finally:
        try:tmp.unlink()
        except FileNotFoundError:pass


def _pip_command():
    if importlib.util.find_spec('pip') is not None:return [sys.executable,'-B','-m','pip']
    try:
        import ensurepip
        wheels=sorted((Path(ensurepip.__file__).parent/'_bundled').glob('pip-*.whl'))
    except (ImportError,OSError,TypeError):wheels=[]
    if not wheels:wheels=sorted((ROOT/'dashboard'/'wheelhouse').glob('pip-*.whl'))
    if not wheels:return None
    code='import sys;sys.path.insert(0,sys.argv.pop(1));from pip._internal.cli.main import main;raise SystemExit(main())'
    return [sys.executable,'-B','-c',code,str(wheels[-1])]


def install(*,root=ROOT,runner=subprocess.run):
    root=Path(root);before=probe(root=root)
    if not before['compatible']:return dict(ok=False,stage='unsupported_python',check=before)
    if before['ok']:return dict(ok=True,stage='already_ready',check=before)
    command=_pip_command()
    if not command:return dict(ok=False,stage='pip_unavailable',check=before)
    wheelhouse=root/'dashboard'/'wheelhouse';offline=wheelhouse.is_dir() and any(wheelhouse.glob('*.whl'))
    passes=[True,False] if offline else [False]
    base=overlay_root(root);base.mkdir(parents=True,exist_ok=True)
    environment=os.environ.copy();environment.pop('PIP_USER',None);environment.pop('PIP_REQUIRE_VIRTUALENV',None)
    for use_offline in passes:
        generation=uuid.uuid4().hex;target=base/generation;target.mkdir()
        args=[*command,'install','--disable-pip-version-check','--no-input','--no-compile','--timeout','30','--retries','2','--target',str(target),
              '-r',str(root/'dashboard'/'requirements-app.txt')]
        if use_offline:args+=['--no-index','--find-links',str(wheelhouse)]
        try:
            result=runner(args,cwd=str(root),env=environment,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except OSError as exc:
            return dict(ok=False,stage='install_failed',error_type=type(exc).__name__,check=before)
        if result.returncode:continue
        report=target/'check.json'
        check=runner([sys.executable,'-B','-X','utf8','-m','dashboard.python_environment','probe','--candidate',str(target),'--output',str(report)],
            cwd=str(root),env=environment,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=180,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:after=json.loads(report.read_text(encoding='utf8'))
        except (OSError,ValueError):after={}
        if check.returncode or not after.get('ok'):return dict(ok=False,stage='verification_failed',check=after)
        atomic_json(base/'current.json',dict(schema='dashboard-python-overlay-v1',generation=generation))
        return dict(ok=True,stage='installed',source='offline_wheels' if use_offline else 'configured_pip_index',check=after)
    return dict(ok=False,stage='install_failed',check=before)


def select(*,root=ROOT):
    root=Path(root);executable=Path(sys.executable).resolve()
    bundled=(root/'runtime'/'python'/'python.exe').resolve()
    value=dict(schema='dashboard-python-selection-v1',mode='bundled' if executable==bundled else 'external')
    if executable!=bundled:value['python']=str(executable)
    atomic_json(root/'dashboard'/'localsetting'/'app'/'python.local.json',value)
    return dict(ok=True,stage='selected',python=str(executable))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('probe','install','select'));parser.add_argument('--output',type=Path)
    parser.add_argument('--candidate',type=Path);args=parser.parse_args()
    try:
        result=probe(candidate=args.candidate) if args.action=='probe' else install() if args.action=='install' else select()
    except Exception as exc:result=dict(ok=False,stage=args.action+'_failed',error_type=type(exc).__name__)
    if args.output:atomic_json(args.output,result)
    else:print(json.dumps(result,ensure_ascii=False))
    return 0 if result.get('ok') else 1


if __name__=='__main__':raise SystemExit(main())

"""Build a dashboard-only Windows package from verified, explicit inputs.

The build uses a new staging directory, tracked source files, a verified Python
archive, a local wheelhouse and an exported data package. It never copies a
developer profile, credential, log, Git directory or original data directory.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import zipfile

from dashboard.data_package import ACTIVE, inspect_archive

ROOT=Path(__file__).resolve().parents[1]
PYTHON_SHA256='9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38'
POWERSHELL_SHA256='ce7484804c0f0ad4dda10c958e71acdaf7eebfb22505c1b480f89e0e9f1da94d'
SOURCE_ROOTS=('dashboard','shared_data','index_strategy','index_futures_basis')
SUFFIXES={'.py','.ps1','.cmd','.vbs','.json','.txt','.ico','.svg'}
PORTABLE_FILES=('启动看板.vbs','Python环境设置.vbs','创建桌面快捷方式.vbs','使用说明.txt')
PORTABLE_ACTIONS={'首次配置.vbs':'--first-setup','下载公盘分红 Excel.vbs':'--download-dividends'}


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def sources():
    raw=subprocess.check_output(['git','-c','core.quotepath=false','ls-files','-z','--',*SOURCE_ROOTS],cwd=ROOT)
    names=raw.decode('utf8').split('\0')
    result=[]
    for name in names:
        if not name:continue
        path=PurePosixPath(name)
        if path.suffix.lower() not in SUFFIXES:continue
        if any(p in {'tests','test','docs','portable','localsetting','runtime','__pycache__'} for p in path.parts):continue
        if any(p in {'backtest','recent_brief'} for p in path.parts) or path.name.startswith(('start_backtest','start_recent_brief','diagnose_recent_brief')):continue
        if path.parts[0]!='dashboard' and path.suffix.lower() in {'.ps1','.cmd','.vbs','.ico','.svg'}:continue
        if path.name in {'APP_RELEASE.json','build_colleague_package.py'} or '.local.' in path.name:continue
        if not (ROOT/name).is_file():raise ValueError('Missing source '+name)
        result.append(name)
    return sorted(result)


def safe(name):
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        raise ValueError('Unsafe archive member')
    return path


def extract_runtime(archive_path, destination, expected):
    if digest(archive_path)!=expected:
        raise ValueError('Runtime archive SHA256 mismatch')
    destination.mkdir(parents=True)
    with zipfile.ZipFile(archive_path) as archive:
        for entry in archive.infolist():
            safe(entry.filename)
            if entry.is_dir():continue
            target=destination/entry.filename;target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(entry) as src,target.open('xb') as dst:shutil.copyfileobj(src,dst)


def coverage(stage):
    from dashboard.marketdata.bars import BarDataset
    from dashboard.marketdata.dividends import read_snapshot

    root=stage/'data'
    active=json.loads((root/ACTIVE).read_text(encoding='utf8'))
    history=[]
    for relative in active['history_roots']:
        dataset=BarDataset(root/relative)
        parts=dataset.snapshot()['parts']
        frequencies={}
        for frequency in sorted({p['frequency'] for p in parts}):
            rows=[p for p in parts if p['frequency']==frequency]
            seen={p['trade_date'] for p in rows}
            frequencies[frequency]=dict(first=min(seen),last=max(seen),sessions=len(seen),partitions=len(rows),
                instruments=len({p['instrument_id'] for p in rows}))
        history.append(dict(dataset=dataset.descriptor['dataset_id'],frequencies=frequencies))
    dividends=[]
    for path in sorted((root/active['dividend_root']).rglob('*.xlsx')):
        snapshot=read_snapshot(path,allow_partial=True)
        dividends.append(dict(file=path.relative_to(stage).as_posix(),business_date=snapshot['date'],
            sha256=snapshot['file_sha256'],rows=len(snapshot['rows'])))
    return history, dividends


def prepare(stage,python_archive,wheels,data_archive,powershell_archive=None):
    stage=Path(stage).resolve();python_archive=Path(python_archive).resolve()
    wheels=Path(wheels).resolve();data_archive=Path(data_archive).resolve()
    if stage.exists():raise FileExistsError('Use a new empty staging directory')
    wheel_files=sorted(wheels.glob('*.whl'))
    if not wheel_files:raise ValueError('Missing offline wheels')
    with zipfile.ZipFile(data_archive) as data:
        data_meta=inspect_archive(data)
    stage.mkdir(parents=True)
    source_hashes={}
    for name in sources():
        target=stage/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/name,target);source_hashes[name]=digest(target)
    for name in PORTABLE_FILES:
        source=ROOT/'dashboard'/'portable'/name
        target=stage/name
        if name.endswith('.txt'):target.write_text(source.read_text(encoding='utf8'),encoding='utf-8-sig')
        else:shutil.copy2(source,target)
        source_hashes['dashboard/portable/'+name]=digest(source)
    launcher=(stage/'启动看板.vbs').read_text(encoding='ascii')
    if launcher.count('mode = ""')!=1:raise ValueError('Portable action anchor changed')
    for name,action in PORTABLE_ACTIONS.items():
        (stage/name).write_text(launcher.replace('mode = ""',f'mode = " {action}"'),encoding='ascii')
    runtime=stage/'runtime'/'python'
    extract_runtime(python_archive,runtime,PYTHON_SHA256)
    if powershell_archive:
        extract_runtime(Path(powershell_archive),stage/'runtime'/'powershell',POWERSHELL_SHA256)
    (runtime/'python313._pth').write_text('\n'.join(['python313.zip','.','..\\..\\','Lib\\site-packages','import site','']),encoding='ascii')
    wheel_target=stage/'dashboard'/'wheelhouse';wheel_target.mkdir(parents=True)
    for wheel in wheel_files:shutil.copy2(wheel,wheel_target/wheel.name)
    packages=runtime/'Lib'/'site-packages';packages.mkdir(parents=True)
    pip_wheels=list(wheel_target.glob('pip-*.whl'))
    if len(pip_wheels)!=1:raise ValueError('Exactly one offline pip wheel is required')
    pip_entry='import sys;sys.path.insert(0,sys.argv.pop(1));from pip._internal.cli.main import main;raise SystemExit(main())'
    cmd=[str(runtime/'python.exe'),'-B','-s','-c',pip_entry,str(pip_wheels[0]),
         'install','--disable-pip-version-check','--no-input','--no-compile',
         '--no-index','--find-links',str(wheel_target),'--target',str(packages),
         '-r',str(stage/'dashboard'/'requirements-app.txt'),'pip']
    env=os.environ.copy()
    for key in ('PIP_USER','PIP_REQUIRE_VIRTUALENV','PYTHONPATH','PYTHONHOME'):env.pop(key,None)
    subprocess.run(cmd,cwd=stage,env=env,check=True,stdin=subprocess.DEVNULL)
    versions=json.loads(subprocess.check_output([str(runtime/'python.exe'),'-B','-s','-c',
        'import importlib.metadata as m,json;print(json.dumps({d.metadata["Name"].lower().replace("_","-"):d.version for d in m.distributions()}))'],
        cwd=stage,env=env))
    from dashboard.python_environment import MODULES
    pinned=stage/'dashboard'/'requirements-colleague-313.txt'
    pinned.write_text(''.join(f'{name}=={versions[name.lower()]}\n' for name in MODULES),encoding='utf8')
    with zipfile.ZipFile(data_archive) as data:
        for name in data_meta['files']:
            safe(name);target=stage/name;target.parent.mkdir(parents=True,exist_ok=True)
            with data.open(name) as src,target.open('xb') as dst:shutil.copyfileobj(src,dst)
    history,dividends=coverage(stage)
    manifest=dict(schema='delta1-colleague-build-v1',python='3.13.17-win-amd64',python_sha256=PYTHON_SHA256,
        source_sha256=source_hashes,data_package_sha256=digest(data_archive),data_package_id=data_meta['package_id'],
        wheel_sha256={wheel.name:digest(wheel) for wheel in wheel_files},python_packages=versions,
        entry_sha256={name:digest(stage/name) for name in (*PORTABLE_FILES,*PORTABLE_ACTIONS)},
        history=history,dividends=dividends,credentials_included=False)
    if powershell_archive:
        manifest['powershell']=dict(version='7.6.9-win-x64',archive_sha256=POWERSHELL_SHA256)
    (stage/'PACKAGE-MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(stage=str(stage),source_files=len(source_hashes),data_files=len(data_meta['files']),wheels=len(wheel_files)),ensure_ascii=False))


def archive(stage,output):
    stage=Path(stage).resolve();output=Path(output).resolve()
    manifest_path=stage/'PACKAGE-MANIFEST.json';manifest=json.loads(manifest_path.read_text(encoding='utf8'))
    if manifest.get('schema')!='delta1-colleague-build-v1':raise ValueError('Invalid staging directory')
    for forbidden in ('dashboard/localsetting','dashboard/runtime','.deps','outputs','.git'):
        if (stage/forbidden).exists():raise ValueError('Staging contains a local profile, runtime log or Git directory')
    files=sorted(p for p in stage.rglob('*') if p.is_file())
    if any(p.name.lower().endswith(('.local.json','.log','.sqlite','.db')) or p.name.lower()=='native.json' for p in files):
        raise ValueError('Staging contains a local setting, log or database')
    expected={n for n in manifest['source_sha256'] if not n.startswith('dashboard/portable/')}
    if expected!=set(sources()):raise ValueError('Source list changed after staging')
    for name,expected_hash in manifest['source_sha256'].items():
        if digest(ROOT/name)!=expected_hash:raise ValueError('Source changed after staging: '+name)
    for name,expected_hash in manifest.get('entry_sha256',{}).items():
        if digest(stage/name)!=expected_hash:raise ValueError('Portable entry changed after staging: '+name)
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    manifest.update(revision=revision,created_utc=datetime.now(timezone.utc).isoformat())
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():raise FileExistsError('Output already exists')
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=5,allowZip64=True) as result:
        for path in files:
            relative=path.relative_to(stage).as_posix();safe(relative)
            result.write(path,'Delta1/'+relative)
    print(json.dumps(dict(output=str(output),bytes=output.stat().st_size,sha256=digest(output),revision=revision),ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare');p.add_argument('--stage',required=True);p.add_argument('--python-archive',required=True)
    p.add_argument('--wheels',required=True);p.add_argument('--data-archive',required=True);p.add_argument('--powershell-archive')
    a=sub.add_parser('archive');a.add_argument('--stage',required=True);a.add_argument('--output',required=True)
    args=parser.parse_args()
    if args.action=='prepare':prepare(args.stage,args.python_archive,args.wheels,args.data_archive,args.powershell_archive)
    else:archive(args.stage,args.output)


if __name__=='__main__':main()

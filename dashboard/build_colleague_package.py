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

from dashboard.data_package import inspect_archive

ROOT=Path(__file__).resolve().parents[1]
PYTHON_SHA256='9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38'
SOURCE_ROOTS=('dashboard','shared_data','index_strategy','index_futures_basis')
SUFFIXES={'.py','.ps1','.cmd','.vbs','.json','.txt','.ico','.svg'}


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
        if path.name in {'APP_RELEASE.json','build_colleague_package.py'} or '.local.' in path.name:continue
        if not (ROOT/name).is_file():raise ValueError('Missing source '+name)
        result.append(name)
    return sorted(result)


def safe(name):
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        raise ValueError('Unsafe archive member')
    return path


def prepare(stage,python_archive,wheels,data_archive):
    stage=Path(stage).resolve();python_archive=Path(python_archive).resolve()
    wheels=Path(wheels).resolve();data_archive=Path(data_archive).resolve()
    if stage.exists():raise FileExistsError('Use a new empty staging directory')
    if digest(python_archive)!=PYTHON_SHA256:raise ValueError('Python SHA256 mismatch')
    wheel_files=sorted(wheels.glob('*.whl'))
    if not wheel_files:raise ValueError('Missing offline wheels')
    with zipfile.ZipFile(data_archive) as data:
        data_meta=inspect_archive(data)
    stage.mkdir(parents=True)
    source_hashes={}
    for name in sources():
        target=stage/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/name,target);source_hashes[name]=digest(target)
    for name in ('启动看板.vbs','Python环境设置.vbs','使用说明.txt'):
        source=ROOT/'dashboard'/'portable'/name
        target=stage/name
        if name.endswith('.txt'):target.write_text(source.read_text(encoding='utf8'),encoding='utf-8-sig')
        else:shutil.copy2(source,target)
        source_hashes['dashboard/portable/'+name]=digest(source)
    runtime=stage/'runtime'/'python';runtime.mkdir(parents=True)
    with zipfile.ZipFile(python_archive) as archive:
        for entry in archive.infolist():
            safe(entry.filename)
            if entry.is_dir():continue
            target=runtime/entry.filename;target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(entry) as src,target.open('xb') as dst:shutil.copyfileobj(src,dst)
    (runtime/'python313._pth').write_text('\n'.join(['python313.zip','.','..\\..\\','Lib\\site-packages','import site','']),encoding='ascii')
    wheel_target=stage/'dashboard'/'wheelhouse';wheel_target.mkdir(parents=True)
    for wheel in wheel_files:shutil.copy2(wheel,wheel_target/wheel.name)
    packages=runtime/'Lib'/'site-packages';packages.mkdir(parents=True)
    cmd=[sys.executable,'-B','-m','pip','install','--disable-pip-version-check','--no-input','--no-compile',
         '--no-index','--find-links',str(wheel_target),'--target',str(packages),
         '-r',str(stage/'dashboard'/'requirements-app.txt'),'pip']
    env=os.environ.copy()
    for key in ('PIP_USER','PIP_REQUIRE_VIRTUALENV','PYTHONPATH','PYTHONHOME'):env.pop(key,None)
    subprocess.run(cmd,cwd=stage,env=env,check=True,stdin=subprocess.DEVNULL)
    with zipfile.ZipFile(data_archive) as data:
        for name in data_meta['files']:
            safe(name);target=stage/name;target.parent.mkdir(parents=True,exist_ok=True)
            with data.open(name) as src,target.open('xb') as dst:shutil.copyfileobj(src,dst)
    manifest=dict(schema='delta1-colleague-build-v1',python='3.13.17-win-amd64',python_sha256=PYTHON_SHA256,
        source_sha256=source_hashes,data_package_sha256=digest(data_archive),data_package_id=data_meta['package_id'],
        wheel_sha256={wheel.name:digest(wheel) for wheel in wheel_files},history_end='2026-10-16',
        dividend_snapshot='2026-09-18',credentials_included=False)
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
    p.add_argument('--wheels',required=True);p.add_argument('--data-archive',required=True)
    a=sub.add_parser('archive');a.add_argument('--stage',required=True);a.add_argument('--output',required=True)
    args=parser.parse_args()
    if args.action=='prepare':prepare(args.stage,args.python_archive,args.wheels,args.data_archive)
    else:archive(args.stage,args.output)


if __name__=='__main__':main()

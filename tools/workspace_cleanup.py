"""Archive old validation output and remove reproducible bytecode, offline.

Default: write a reviewable plan. --apply consumes that exact plan, verifies a
ZIP and every source hash, then removes only the verified ignored copies.
Business data, runtime packages, configuration, exports and other worktrees are
outside this tool's scope. No recursive delete, process control or network.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time
import uuid
import zipfile

VALIDATION_DIRS=frozenset('''app_exit app_v6_temp app_vpn calendar-health-tmp
company_connection_20261026 desktop_presentation_20261026 instance_handover_20261026
lending_filters lock_diagnostics metric_implementation metric_redesign
numeric_company_launcher numeric_integration numeric_launcher_folder
numeric_launcher_regression numeric_realtime numeric_refresh numeric_startup
numeric_startup_permission numeric_vpn orphan_service overview_20261026
overview_implementation overview_repair_20261027 overview_report3_20261027
pair_intraday pair_metrics_review pair_metrics_test_tmp pair_reconstruction
pair_rework presentation_release short_tests_tmp short_v2_verify short_verify
startup_diagnostics tmp ui_config_fix ui_launcher_fix ui_simplification'''.split())
VALIDATION_FILES=frozenset(('calendar-health-tests.log','calendar-preferred-tests.log',
    'numeric_launcher_regression_tests.log','wind_diagnostics_preview.txt'))
SOURCE_ROOTS=('dashboard','index_strategy','index_futures_basis','script_making','securities_lending','shared_data','tests','tools')
PRIVATE_DIRS=frozenset(('.git','.deps','data','cache','runtime','localsetting','localsettings',
    'materials','inputs','outputs','exports','logs','node_modules','local_artifacts'))


class UnsafePath(ValueError):pass


def is_reparse(path):
    info=path.lstat()
    return path.is_symlink() or bool(getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024))


def checked(root,relative):
    """Check lexical and resolved boundaries, including every reparse ancestor."""
    root=Path(root).resolve();relative=Path(relative)
    if relative.is_absolute() or not relative.parts or any(p in ('.','..','.git') for p in relative.parts):
        raise UnsafePath('Path must be below the selected workspace')
    path=root/relative
    if not path.resolve().is_relative_to(root) or path.resolve()==root:raise UnsafePath('Path escapes workspace')
    cursor=path
    while cursor!=root:
        if cursor.exists() or cursor.is_symlink():
            if is_reparse(cursor):raise UnsafePath('Reparse points are preserved')
        cursor=cursor.parent
    return path


def archive_member(relative):
    parts=Path(relative).parts
    return len(parts)>=2 and parts[0]=='.deps' and (
        parts[1] in VALIDATION_DIRS or len(parts)==2 and parts[1] in VALIDATION_FILES)


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def remove_verified_file(path):
    """Windows Git fixture packs can be read-only; only handle that attribute."""
    try:path.unlink()
    except PermissionError:
        if not getattr(path.stat(),'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_READONLY',1):raise
        path.chmod(stat.S_IREAD|stat.S_IWRITE)
        path.unlink()


def tracked_files(root):
    raw=subprocess.check_output(['git','ls-files','-z'],cwd=root)
    return set(raw.decode('utf8').split('\0'))-{''}


def configuration_references(root,extra=()):
    """Retain validation directories explicitly referenced by local App settings."""
    candidates={Path(p).resolve() for p in extra}
    for base in (root,*[root/name for name in SOURCE_ROOTS if name not in ('tests','tools')]):
        if not base.is_dir():continue
        candidates.update(base.glob('*.local.json'))
        for relative in ('localsetting/native.json','localsetting/app/native.json','localsetting/numeric_excel/native.json','localsetting/data.local.json'):
            path=base/relative
            if path.is_file():candidates.add(path)
    blocked=set();present=[];prefix=str(root/'.deps').replace('\\','/').casefold()+'/'
    for path in sorted(candidates):
        if not path.is_file():raise UnsafePath('Selected configuration is unavailable')
        present.append(str(path))
        try:data=json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError,ValueError):blocked.update(VALIDATION_DIRS|VALIDATION_FILES);continue
        stack=[data]
        while stack:
            item=stack.pop()
            if isinstance(item,dict):stack.extend(item.values())
            elif isinstance(item,list):stack.extend(item)
            elif isinstance(item,str):
                value=item.replace('\\','/').casefold()
                if '.deps/' not in value:continue
                try:
                    candidate=Path(item.replace('\\','/'))
                    value=str((candidate if candidate.is_absolute() else root/candidate).resolve()).replace('\\','/').casefold()
                except (OSError,ValueError):blocked.update(VALIDATION_DIRS|VALIDATION_FILES);continue
                suffix=value[len(prefix):] if value.startswith(prefix) else None
                if suffix is not None:blocked.add(suffix.split('/')[0])
    return blocked,present


def inspect_tree(root,path):
    files=[];directories=[];stack=[path]
    while stack:
        item=stack.pop();checked(root,item.relative_to(root))
        if item.is_dir():directories.append(item.relative_to(root).as_posix());stack.extend(item.iterdir())
        else:
            info=item.stat();files.append(dict(path=item.relative_to(root).as_posix(),bytes=info.st_size,mtime_ns=info.st_mtime_ns))
    return files,directories


def bytecode_candidates(root,tracked):
    result=[]
    for name in SOURCE_ROOTS:
        parent=root/name
        if not parent.is_dir():continue
        for base,dirs,files in os.walk(parent,followlinks=False):
            current=Path(base)
            dirs[:]=[d for d in dirs if d not in PRIVATE_DIRS and not is_reparse(current/d)]
            if current.name!='__pycache__':continue
            for name in files:
                path=current/name;relative=path.relative_to(root).as_posix()
                source=current.parent/(name.split('.')[0]+'.py')
                if path.suffix=='.pyc' and source.is_file() and source.relative_to(root).as_posix() in tracked and relative not in tracked:
                    checked(root,relative);result.append(dict(path=relative,bytes=path.stat().st_size))
    return sorted(result,key=lambda r:r['path'])


def plan(root,*,tracked=None,min_age_hours=24,now=None,configurations=()):
    root=Path(root).resolve();tracked=tracked_files(root) if tracked is None else tracked
    cutoff=(time.time() if now is None else now)-min_age_hours*3600
    files=[];directories=[];excluded=[];referenced,configs=configuration_references(root,configurations)
    for name in sorted(VALIDATION_DIRS|VALIDATION_FILES):
        path=root/'.deps'/name
        if not path.exists():continue
        if name.casefold() in referenced:
            excluded.append(dict(path=path.relative_to(root).as_posix(),reason='referenced_by_configuration'));continue
        try:members,folders=inspect_tree(root,path)
        except (UnsafePath,OSError) as exc:
            excluded.append(dict(path=path.relative_to(root).as_posix(),reason=type(exc).__name__));continue
        relative=path.relative_to(root).as_posix()
        if any(p==relative or p.startswith(relative+'/') for p in tracked):
            excluded.append(dict(path=relative,reason='tracked_files_preserved'));continue
        newest=max([path.stat().st_mtime,*[r['mtime_ns']/1e9 for r in members]])
        if newest>cutoff:
            excluded.append(dict(path=relative,reason='recent_output_preserved'));continue
        files.extend(members);directories.extend(folders)
    cache=bytecode_candidates(root,tracked)
    return dict(schema='workspace-cleanup-plan-v1',root=str(root),created_at=datetime.now(timezone.utc).isoformat(),
        min_age_hours=min_age_hours,archive_files=sorted(files,key=lambda r:r['path']),
        archive_directories=sorted(directories),bytecode=cache,excluded=excluded,configuration_files=configs,
        archive_source_bytes=sum(r['bytes'] for r in files),bytecode_bytes=sum(r['bytes'] for r in cache))


def write_json(root,path,value):
    path=checked(root,path.relative_to(root));path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    checked(root,temporary.relative_to(root))
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    os.replace(temporary,path)


def verify_archive(path,entries):
    expected={r['path']:r for r in entries}
    with zipfile.ZipFile(path) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)) or set(names)!=set(expected)|{'archive_manifest.json'}:
            raise UnsafePath('Archive member list mismatch')
        for name,row in expected.items():
            value=hashlib.sha256();size=0
            with archive.open(name) as source:
                for block in iter(lambda:source.read(1024*1024),b''):value.update(block);size+=len(block)
            if value.hexdigest()!=row['sha256'] or size!=row['bytes']:raise UnsafePath('Archive content mismatch')
        manifest=json.loads(archive.read('archive_manifest.json'))
        if manifest.get('files')!=entries:raise UnsafePath('Archive manifest mismatch')


def apply(root,value,*,tracked=None,progress=lambda message:None):
    root=Path(root).resolve();tracked=tracked_files(root) if tracked is None else tracked
    if value.get('schema')!='workspace-cleanup-plan-v1' or Path(value['root']).resolve()!=root:
        raise UnsafePath('Plan belongs to a different workspace')
    files=value['archive_files'];cache=value['bytecode']
    referenced,_=configuration_references(root,value.get('configuration_files',()))
    if len({r['path'] for r in files+cache})!=len(files+cache):raise UnsafePath('Duplicate planned path')
    # Validate the entire plan before creating or removing anything.
    for row in files:
        path=checked(root,row['path'])
        if not archive_member(row['path']) or row['path'] in tracked:raise UnsafePath('Not a validation artifact')
        if Path(row['path']).parts[1].casefold() in referenced:raise UnsafePath('Source is now referenced by App settings')
        info=path.stat()
        if not path.is_file() or (info.st_size,info.st_mtime_ns)!=(row['bytes'],row['mtime_ns']):
            raise UnsafePath('Source changed since plan')
    permitted_cache={r['path'] for r in bytecode_candidates(root,tracked)}
    if any(r['path'] not in permitted_cache for r in cache):raise UnsafePath('Not reproducible bytecode')
    for relative in value['archive_directories']:
        checked(root,relative)
        if not archive_member(relative):raise UnsafePath('Not a validation directory')
        if Path(relative).parts[1].casefold() in referenced:raise UnsafePath('Directory is now referenced by App settings')
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
    output=checked(root,Path('local_artifacts/archives/validation')/stamp);output.mkdir(parents=True)
    archive_path=output/'validation.zip';manifest=[]
    with zipfile.ZipFile(archive_path,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
        for i,row in enumerate(files):
            path=checked(root,row['path']);hash_value=hashlib.sha256()
            with path.open('rb') as source,archive.open(row['path'],'w',force_zip64=True) as target:
                for block in iter(lambda:source.read(1024*1024),b''):hash_value.update(block);target.write(block)
            manifest.append(dict(row,sha256=hash_value.hexdigest()))
            if (i+1)%5000==0:progress('Archived '+str(i+1)+' files')
        archive.writestr('archive_manifest.json',json.dumps(dict(root=str(root),files=manifest),ensure_ascii=False))
    progress('Verifying archive hashes')
    verify_archive(archive_path,manifest)
    # Recheck every original before the first deletion. A concurrent change
    # retains the originals; the completed archive remains a recoverable copy.
    for row in manifest:
        path=checked(root,row['path']);info=path.stat()
        if (info.st_size,info.st_mtime_ns)!=(row['bytes'],row['mtime_ns']) or digest(path)!=row['sha256']:
            raise UnsafePath('Concurrent source change; originals preserved')
    report=dict(schema='workspace-cleanup-result-v1',root=str(root),archive=str(archive_path.relative_to(root)),
        archive_bytes=archive_path.stat().st_size,archive_source_bytes=value['archive_source_bytes'],
        archived_files=len(manifest),deleted_files=0,deleted_bytes=0,bytecode_removed=0,bytecode_bytes=0,retained=[],
        status='verified_archive_before_removing_copies')
    write_json(root,output/'result.json',report)
    progress('Archive verified; removing only verified copies')
    for row in manifest:
        path=checked(root,row['path'])
        try:
            info=path.stat()
            if (info.st_size,info.st_mtime_ns)!=(row['bytes'],row['mtime_ns']):
                report['retained'].append(dict(path=row['path'],reason='changed_after_verification'));continue
            remove_verified_file(path);report['deleted_files']+=1;report['deleted_bytes']+=row['bytes']
        except OSError as exc:report['retained'].append(dict(path=row['path'],reason=type(exc).__name__))
    for relative in sorted(value['archive_directories'],key=lambda p:len(Path(p).parts),reverse=True):
        path=checked(root,relative)
        try:path.rmdir()
        except OSError:pass  # Never remove a nonempty directory recursively.
    for row in cache:
        path=checked(root,row['path'])
        try:path.unlink();report['bytecode_removed']+=1;report['bytecode_bytes']+=row['bytes']
        except OSError as exc:report['retained'].append(dict(path=row['path'],reason=type(exc).__name__))
    for relative in sorted({str(Path(r['path']).parent) for r in cache},key=len,reverse=True):
        try:checked(root,relative).rmdir()
        except OSError:pass
    report.update(status='complete' if not report['retained'] else 'partial',
        freed_bytes=report['deleted_bytes']+report['bytecode_bytes']-report['archive_bytes'])
    write_json(root,output/'result.json',report)
    write_json(root,output/'source_manifest.json',dict(files=manifest))
    write_json(root,root/'local_artifacts/LATEST_CLEANUP.json',report)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',type=Path,metavar='PLAN',help='Apply a previously generated plan')
    parser.add_argument('--config',action='append',type=Path,default=[],help='Additional existing App config to protect (plan only)')
    args=parser.parse_args(argv);root=Path(__file__).resolve().parents[1]
    actual=subprocess.check_output(['git','rev-parse','--show-toplevel'],cwd=root,text=True).strip()
    if Path(actual).resolve()!=root:raise UnsafePath('Run from this tool repository')
    if args.apply:
        source=checked(root,args.apply.resolve().relative_to(root))
        result=apply(root,json.loads(source.read_text(encoding='utf8')),progress=lambda m:print(m,flush=True))
    else:
        result=plan(root,configurations=args.config);count=len(result['archive_files']);path=root/'local_artifacts/cleanup'/('plan-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.json')
        write_json(root,path,result)
        result={k:v for k,v in result.items() if k not in ('archive_files','archive_directories','bytecode')}
        result.update(plan=str(path.relative_to(root)),archive_files=count)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())

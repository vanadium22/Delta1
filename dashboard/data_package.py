"""Portable, additive dashboard-only data package. No Wind paths are written."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path,PurePosixPath
import uuid
import zipfile

from .marketdata.bars import BarDataset,_atomic_bytes,_json_bytes,_writer_lock
from .marketdata.history_publication import maintenance_root,read_publication

BASE='market/index_futures/dashboard'
ACTIVE=BASE+'/active_package.json'
SCHEMA='delta1_dashboard_data_package_v1'


def digest(data):return hashlib.sha256(data).hexdigest()


def safe_relative(name):
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name or str(p)!=name:
        raise ValueError('Unsafe package path')
    return p


def export_package(local_root,output):
    config=json.loads((Path(local_root)/'native.json').read_text(encoding='utf8'))
    stores={}
    for path in config['history_roots']:
        s=BarDataset(path);stores[s.descriptor['dataset_id']]=s
    pointer=maintenance_root(config['history_roots'])/'publication.json'
    snapshots=read_publication(pointer,stores) if pointer.exists() else {k:s.snapshot() for k,s in stores.items()}
    identifier=datetime.now(timezone.utc).strftime('%y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:4]
    prefix=BASE+'/imports/'+identifier
    files={};roots=[];source_versions={}
    for i,(key,store) in enumerate(stores.items()):
        snap=snapshots[key];root=prefix+f'/s{i+1}';roots.append(root);source_versions[key]=snap['version']
        descriptor={k:v for k,v in snap.get('descriptor',store.descriptor).items() if k not in ('base_dataset','merge_policy')}
        files['data/'+root+'/dataset.json']=_json_bytes(descriptor)
        parts=[];counts=Counter()
        for part in snap['parts']:
            path=store._path(part['path'])
            if digest(path.read_bytes())!=part['sha256']:raise ValueError('Source partition checksum mismatch')
            day=part['trade_date'];directory=f"data/{part['frequency']}/{part['instrument_id']}/{day[:4]}/{day[5:7]}"
            counts[(directory,day)]+=1;number=counts[(directory,day)]
            relative=directory+'/'+day+(f'.{number}' if number>1 else '')+'.parquet'
            safe_relative(relative)
            files['data/'+root+'/'+relative]=path
            parts.append({**part,'path':relative})
        version=uuid.uuid4().hex
        manifest={**snap,'descriptor':descriptor,'parts':parts,'version':version,'previous_version':None,
            'checkpoint':{'portable_source_version':snap['version'],'package_id':identifier}}
        raw=_json_bytes(manifest);relative='versions/'+version+'.json'
        files['data/'+root+'/'+relative]=raw
        files['data/'+root+'/current.json']=_json_bytes(dict(version=version,manifest=relative,sha256=digest(raw)))
    reference=prefix+'/reference.json'
    ref=json.loads(Path(config['reference_file']).read_text(encoding='utf8'))
    files['data/'+reference]=_json_bytes(ref)
    dividend_root=prefix+'/dividends'
    files['data/'+dividend_root+'/README.txt']='历史分红快照；已有公司分红目录优先使用，新增合约缺分红时沿用前一到期合约。\n'.encode('utf8')
    for path in sorted(Path(config.get('dividend_root','')).glob('*.xlsx')):
        if not path.name.startswith('~$'):files['data/'+dividend_root+'/'+path.name]=path
    activation=dict(schema=SCHEMA,package_id=identifier,history_roots=roots,reference_file=reference,dividend_root=dividend_root)
    notes=pointer.parent/'quality_notes.json'
    if notes.exists():
        activation['quality_notes_file']=prefix+'/quality_notes.json'
        files['data/'+activation['quality_notes_file']]=notes.read_bytes()
    files['data/'+ACTIVE]=_json_bytes(activation)
    metadata=dict(schema=SCHEMA,package_id=identifier,source_versions=source_versions,files={})
    for name,value in files.items():
        raw=value.read_bytes() if isinstance(value,Path) else value
        metadata['files'][name]=dict(size=len(raw),sha256=digest(raw))
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_suffix(output.suffix+'.tmp')
    with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        archive.writestr('PACKAGE.json',_json_bytes(metadata))
        for name,value in files.items():
            raw=value.read_bytes() if isinstance(value,Path) else value
            if digest(raw)!=metadata['files'][name]['sha256']:raise ValueError('Source changed while packaging')
            archive.writestr(name,raw)
    temporary.replace(output)
    receipt=dict(package=str(output.resolve()),package_id=identifier,files=len(files),bytes=output.stat().st_size,sha256=digest(output.read_bytes()),source_versions=source_versions)
    _atomic_bytes(output.with_suffix('.receipt.json'),_json_bytes(receipt))
    return receipt


def inspect_archive(archive):
    metadata=json.loads(archive.read('PACKAGE.json'))
    if metadata.get('schema')!=SCHEMA:raise ValueError('Unsupported data package')
    identifier=metadata['package_id'];safe_relative(identifier)
    if '/' in identifier:raise ValueError('Invalid package identity')
    allowed='data/'+BASE+'/imports/'+identifier+'/'
    listed=set(metadata['files'])|{'PACKAGE.json'}
    if set(archive.namelist())!=listed or len(archive.namelist())!=len(listed):raise ValueError('Unlisted or duplicate archive members')
    for name,info in metadata['files'].items():
        safe_relative(name)
        if not(name.startswith(allowed) or name=='data/'+ACTIVE):raise ValueError('Package attempts to write outside dashboard imports')
        entry=archive.getinfo(name)
        if entry.file_size!=info['size'] or entry.file_size>200_000_000:raise ValueError('Package size mismatch')
        raw=archive.read(name)
        if digest(raw)!=info['sha256']:raise ValueError('Package checksum mismatch')
    activation=json.loads(archive.read('data/'+ACTIVE))
    if activation.get('schema')!=SCHEMA or activation.get('package_id')!=identifier:raise ValueError('Invalid activation manifest')
    for path in [*activation['history_roots'],activation['reference_file'],activation['dividend_root'],*([activation['quality_notes_file']] if activation.get('quality_notes_file') else [])]:
        safe_relative(path)
        if not path.startswith(BASE+'/imports/'+identifier+'/'):raise ValueError('Invalid activation target')
    return metadata


def install_package(package,data_root):
    root=Path(data_root).resolve();written=0;unchanged=0
    if (root/BASE).resolve() != root/BASE:
        raise ValueError('Dashboard package directory cannot redirect to another location')
    with zipfile.ZipFile(package) as archive:
        metadata=inspect_archive(archive)
        with _writer_lock(root/BASE/'package_install'):
            targets={}
            for name,info in metadata['files'].items():
                target=(root/name.removeprefix('data/')).resolve()
                if not target.is_relative_to(root/BASE):raise ValueError('Package target escapes dashboard directory')
                if name!='data/'+ACTIVE and target.exists() and digest(target.read_bytes())!=info['sha256']:
                    raise ValueError('Existing file conflict; no data overwritten')
                targets[name]=target
            # Existing files are immutable and never replaced. Activation is last.
            for name,target in targets.items():
                if name=='data/'+ACTIVE:continue
                if target.exists():unchanged+=1;continue
                _atomic_bytes(target,archive.read(name));written+=1
            old=root/ACTIVE
            if old.exists():
                backup=root/BASE/'package_install'/('previous-'+digest(old.read_bytes())[:16]+'.json')
                if not backup.exists():_atomic_bytes(backup,old.read_bytes())
            _atomic_bytes(old,archive.read('data/'+ACTIVE))
    return dict(package_id=metadata['package_id'],written=written,unchanged=unchanged,wind_policy='untouched',data_root=str(root))


def activate_config(config,local_root,data_root):
    """Rebase portable data paths, retaining company credentials and Wind files."""
    root=Path(data_root).resolve();active=root/ACTIVE
    if not active.exists():return config
    value=json.loads(active.read_text(encoding='utf8'));identifier=value.get('package_id','')
    safe_relative(identifier)
    if value.get('schema')!=SCHEMA or '/' in identifier:raise ValueError('Invalid active data package')
    if config.get('history_package_id')==identifier:return config
    def resolve(relative):
        safe_relative(relative);path=(root/relative).resolve()
        if not path.is_relative_to(root/BASE/'imports'/identifier) or not path.exists():raise ValueError('Incomplete imported data package')
        return str(path)
    roots=[resolve(p) for p in value['history_roots']]
    for path in roots:BarDataset(path).snapshot()
    candidate={**config,'history_roots':roots,'reference_file':resolve(value['reference_file']),
        'history_package_id':identifier,'allow_unverified':True,'dashboard_mode':'nonregression','dividend_missing_policy':'previous_contract'}
    candidate['history_quality_notes']=resolve(value['quality_notes_file']) if value.get('quality_notes_file') else ''
    existing_dividends=Path(config['dividend_root']) if config.get('dividend_root') else None
    if existing_dividends is None or not any(p.is_file() and not p.name.startswith('~$') for p in existing_dividends.glob('*.xlsx')):
        candidate['dividend_root']=resolve(value['dividend_root'])
    if not config.get('realtime_root') or not Path(config['realtime_root']).exists():candidate['realtime_root']=str(root/BASE/'realtime')
    local=Path(local_root);path=local/'native.json'
    if path.exists():_atomic_bytes(local/('native.before-package-'+identifier+'.json'),path.read_bytes())
    _atomic_bytes(path,_json_bytes(candidate));return candidate


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    export=sub.add_parser('export');export.add_argument('--local-root',type=Path,default=Path(__file__).parent/'localsetting');export.add_argument('--output',type=Path,required=True)
    install=sub.add_parser('install');install.add_argument('package',type=Path);install.add_argument('--data-root',type=Path,default=Path(__file__).resolve().parents[1]/'data')
    args=parser.parse_args()
    result=export_package(args.local_root,args.output) if args.action=='export' else install_package(args.package,args.data_root)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()

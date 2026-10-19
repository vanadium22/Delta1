"""Explicit additive migration of registered dashboard stores; no config edits.

Stop collectors before running. Old files/manifests remain valid for pinned
readers. Only active indexes advance, after full input validation and backups.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid

from .marketdata.bars import BarDataset, VERSION, _atomic_bytes, _json_bytes, _writer_lock
from .marketdata.history_publication import maintenance_root, read_publication, publish, sync_current
from index_strategy.instant_dld.short_files import publish_bytes
from index_strategy.instant_dld.realtime_store import DB_RELATIVE, WriterLock


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def short_name(name, suffix='parquet'):
    return bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:\.[2-9]\d*|\.1\d+)?\.'+suffix, name))


def stamp():
    return datetime.now(timezone.utc).strftime('%y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:4]


def migrate_history(roots):
    if not roots:
        return dict(changed=0, parts=0)
    stores={}
    for root in roots:
        store=BarDataset(root)
        descriptor=store.descriptor
        if descriptor.get('schema_version')!=VERSION:
            raise ValueError('Only registered dashboard histories can be migrated')
        key=descriptor['dataset_id']
        if key in stores:
            raise ValueError('Duplicate history dataset')
        stores[key]=store
    maintenance=maintenance_root(roots);pointer=maintenance/'publication.json'
    with ExitStack() as locks:
        locks.enter_context(_writer_lock(maintenance))
        for store in sorted(stores.values(),key=lambda s:str(s.root)):
            locks.enter_context(_writer_lock(store.root))
        snapshots=read_publication(pointer,stores) if pointer.exists() else {k:s.snapshot() for k,s in stores.items()}
        total=0
        for key,snap in snapshots.items():
            for part in snap['parts']:
                if sha(stores[key]._path(part['path']).read_bytes())!=part['sha256']:
                    raise ValueError('Source partition checksum mismatch; indexes not changed')
                total+=1
        changes={k:[p for p in snap['parts'] if not short_name(Path(p['path']).name)] for k,snap in snapshots.items()}
        count=sum(map(len,changes.values()))
        if not count:
            if pointer.exists():
                # Resume compatibility-pointer updates after an interrupted commit.
                sync_current(stores,snapshots)
            return dict(changed=0,parts=total)
        backup=maintenance/'short_paths'/stamp()
        old_publication=json.loads(pointer.read_text(encoding='utf8')) if pointer.exists() else None
        original=dict(publication=old_publication,current={k:json.loads((s.root/'current.json').read_text(encoding='utf8'))
            if (s.root/'current.json').exists() else None for k,s in stores.items()})
        _atomic_bytes(backup/'before.json',_json_bytes(original))
        updated={};mapping=[]
        for key,store in stores.items():
            snap=snapshots[key]
            if not changes[key]:
                updated[key]=snap
                continue
            parts=[]
            for part in snap['parts']:
                source=store._path(part['path'])
                if short_name(source.name):
                    parts.append(part)
                    continue
                raw=source.read_bytes()
                if sha(raw)!=part['sha256']:
                    raise ValueError('Source changed during migration')
                target=publish_bytes(raw,source.parent,part['trade_date'])
                relative=target.relative_to(store.root).as_posix()
                parts.append({**part,'path':relative})
                mapping.append(dict(dataset=key,old=part['path'],new=relative,sha256=part['sha256']))
            version=uuid.uuid4().hex
            updated[key]={**snap,'version':version,'previous_version':snap['version'],'parts':parts}
            _atomic_bytes(store.root/'versions'/f'{version}.json',_json_bytes(updated[key]))
        _atomic_bytes(backup/'mapping.json',_json_bytes(mapping))
        # Preserve maintenance provenance; publication is the single commit point.
        extra={k:v for k,v in (old_publication or {}).items() if k not in ('roots','datasets')}
        publish(pointer,stores,updated,**extra)
        sync_current(stores,updated)
        result=dict(changed=count,parts=total,backup=str(backup),old_files='preserved')
        _atomic_bytes(backup/'done.json',_json_bytes(result))
        return result


def migrate_realtime(root):
    root=Path(root).resolve();database=root/DB_RELATIVE
    if not database.exists():
        return dict(changed=0,reason='no realtime database')
    def inside(relative):
        path=(root/relative).resolve()
        if not path.is_relative_to(root) or Path(relative).is_absolute():
            raise ValueError('Realtime catalogue escapes root')
        return path
    lock=WriterLock(root)
    try:
        with closing(sqlite3.connect(database.as_uri()+'?mode=rw',uri=True)) as connection, connection:
            connection.row_factory=sqlite3.Row
            if connection.execute('PRAGMA user_version').fetchone()[0]!=4:
                raise ValueError('Realtime migration requires schema v4; no schema changes performed')
            parts=connection.execute('SELECT * FROM parquet_parts').fetchall()
            jobs=[]
            for part in parts:
                source=inside(part['path']);raw=source.read_bytes()
                if not short_name(source.name):
                    jobs.append((part,sha(raw)))
            raw_jobs=[]
            for event in connection.execute("SELECT id,description FROM events WHERE kind='raw_http_batch'"):
                reference=json.loads(event['description']);source=inside(reference['path'])
                raw=source.read_bytes()
                if sha(raw)!=reference['sha256']:
                    raise ValueError('Raw evidence checksum mismatch; indexes not changed')
                if not re.fullmatch(r'p\d+-b\d+(?:\.\d+)?\.json',source.name):
                    envelope=json.loads(raw);meta=envelope['request_and_collection']
                    prefix=f"p{int(meta.get('poll',0))}-b{int(meta.get('batch',0))}"
                    raw_jobs.append((event['id'],reference,prefix))
            if not jobs and not raw_jobs:
                return dict(changed=0,raw_changed=0,parts=len(parts))
            backup=root/'live'/'short_paths'/stamp();backup.mkdir(parents=True)
            with closing(sqlite3.connect(backup/'before.sqlite3')) as saved:
                connection.backup(saved)
            mappings=[]
            connection.execute('BEGIN IMMEDIATE')
            for part,digest in jobs:
                source=inside(part['path']);raw=source.read_bytes()
                if sha(raw)!=digest:
                    raise ValueError('Realtime source changed during migration')
                target=publish_bytes(raw,source.parent,part['capture_date'])
                relative=target.relative_to(root).as_posix()
                connection.execute('UPDATE parquet_parts SET path=? WHERE path=?',(relative,part['path']))
                mappings.append(dict(old=part['path'],new=relative,sha256=digest))
            for event_id,reference,prefix in raw_jobs:
                source=inside(reference['path']);raw=source.read_bytes()
                if sha(raw)!=reference['sha256']:
                    raise ValueError('Raw evidence changed during migration')
                target=publish_bytes(raw,source.parent,prefix,'.json')
                relative=target.relative_to(root).as_posix()
                connection.execute('UPDATE events SET description=? WHERE id=?',
                    (_json_bytes({**reference,'path':relative}).decode('utf8'),event_id))
                mappings.append(dict(old=reference['path'],new=relative,sha256=reference['sha256']))
            _atomic_bytes(backup/'mapping.json',_json_bytes(mappings))
            connection.commit()
            return dict(changed=len(jobs),raw_changed=len(raw_jobs),parts=len(parts),backup=str(backup),old_files='preserved')
    finally:
        lock.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-root',type=Path,help='Read native.json; never rewrite it')
    parser.add_argument('--history-root',type=Path,action='append',default=[])
    parser.add_argument('--realtime-root',type=Path)
    args=parser.parse_args()
    roots=list(args.history_root);realtime=args.realtime_root
    if args.local_root:
        config=json.loads((args.local_root/'native.json').read_text(encoding='utf-8-sig'))
        roots.extend(config.get('history_roots',[]))
        realtime=realtime or config.get('realtime_root')
    if not roots and not realtime:
        parser.error('Specify a config or explicit registered store paths')
    result=dict(history=migrate_history(roots))
    if realtime:
        result['realtime']=migrate_realtime(realtime)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()

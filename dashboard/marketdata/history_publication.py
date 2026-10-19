"""One atomic pointer for a collection of immutable history manifests."""
import hashlib
import json
import os
from pathlib import Path
from .bars import _atomic_bytes, _json_bytes


def maintenance_root(roots):
    paths = sorted(str(Path(p).resolve()) for p in roots)
    if not paths or any(Path(p).drive.upper() == 'Z:' for p in paths):
        raise ValueError('History roots must be local registered datasets')
    scope = hashlib.sha256(_json_bytes(paths)).hexdigest()[:16]
    return Path(os.path.commonpath([str(Path(p).parent) for p in paths])) / '_maintenance' / scope


def read_publication(path, datasets):
    value = json.loads(Path(path).read_text(encoding='utf8'))
    if value['roots'] != {k: str(v.root) for k,v in datasets.items()}:
        raise ValueError('Published history roots do not match registered datasets')
    result = {}
    for key, store in datasets.items():
        item = value['datasets'][key]
        if item['version'] is None:
            result[key] = dict(version=None, parts=[], checkpoint={}, descriptor=store.descriptor)
            continue
        raw = store._path('versions/'+item['version']+'.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('Published history manifest checksum mismatch')
        result[key] = store.snapshot(item['version'])
    return result


def publish(path, datasets, snapshots, **extra):
    value = dict(roots={k: str(v.root) for k,v in datasets.items()}, datasets={}, **extra)
    for key, store in datasets.items():
        version = snapshots[key]['version']
        value['datasets'][key] = dict(version=version, sha256=hashlib.sha256(
            store._path('versions/'+version+'.json').read_bytes()).hexdigest() if version else None)
    _atomic_bytes(Path(path), _json_bytes(value))
    return value


def sync_current(datasets, snapshots):
    """Compatibility pointers follow the already committed joint generation."""
    for key, store in datasets.items():
        version = snapshots[key]['version']
        if version:
            relative = 'versions/'+version+'.json'
            _atomic_bytes(store.root/'current.json', _json_bytes(dict(version=version,
                manifest=relative, sha256=hashlib.sha256(store._path(relative).read_bytes()).hexdigest())))

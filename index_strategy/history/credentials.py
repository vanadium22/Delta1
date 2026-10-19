"""Load the corporate credential provider without adding global import paths."""
import importlib.util
from pathlib import Path


def provider():
    path = Path(__file__).resolve().parents[3] / 'dolphindb_data/protected_config.py'
    if not path.is_file():
        from . import protected_config
        return protected_config
    spec = importlib.util.spec_from_file_location('swhy_protected_config', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_config(path):
    return provider().load_config(path)

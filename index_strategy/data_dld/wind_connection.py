"""Read-only Wind probes with untracked local settings or environment variables."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if importlib.util.find_spec("oracledb") is None and (HERE / ".deps").is_dir():
    sys.path.insert(0, str(HERE / ".deps"))


def credentials(source: Path | None = None) -> dict[str, str]:
    values = {}
    env_names = {"user": "WIND_DB_USER", "password": "WIND_DB_PASSWORD", "dsn": "WIND_DB_DSN"}
    if not all(os.environ.get(name) for name in env_names.values()):
        path = Path(source or os.environ.get("WIND_DB_CONFIG") or HERE.parents[1] / "localsetting" / "wind_db.json")
        if path.is_file():
            values = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(values, dict):
                raise ValueError("Wind connection settings must be a JSON object.")
            values = {key: values.get(key) for key in env_names}
    for key, name in env_names.items():
        if os.environ.get(name):
            values[key] = os.environ[name]
    if any(not isinstance(values.get(key), str) or not values[key].strip() for key in env_names):
        raise ValueError("Missing Wind settings: use localsetting/wind_db.json or WIND_DB_USER/PASSWORD/DSN.")
    return values


def connect():
    import oracledb

    client = os.environ.get("ORACLE_CLIENT_LIB_DIR")
    if not client:
        candidates = sorted((HERE / ".runtime").glob("instantclient_*/oci.dll"))
        if candidates:
            client = str(candidates[-1].parent)
    if client:
        oracledb.init_oracle_client(lib_dir=client)
    conf = credentials()
    params = oracledb.ConnectParams()
    params.parse_connect_string(conf.pop("dsn"))
    params.set(tcp_connect_timeout=8, retry_count=0)
    db = oracledb.connect(**conf, dsn=params.get_connect_string())
    db.call_timeout = 30000
    return db


def select(db, sql: str, binds: dict | None = None, limit: int = 10000):
    """Only SELECTs, bounded client fetch; caller must also bound expensive SQL."""
    if not sql.lstrip().upper().startswith("SELECT "):
        raise ValueError("Probe accepts SELECT statements only.")
    with db.cursor() as cur:
        cur.arraysize = min(1000, limit + 1)
        cur.execute(sql, binds or {})
        columns = [item[0] for item in cur.description]
        rows = cur.fetchmany(limit + 1)
        if len(rows) > limit:
            raise ValueError(f"Result exceeded probe limit ({limit}); narrow the query.")
        return [dict(zip(columns, row)) for row in rows]


def safe_error(exc: Exception) -> str:
    message = f"{type(exc).__name__}: {exc}"
    try:
        message = message.replace(credentials()["password"], "<redacted>")
    except Exception:
        pass
    return message

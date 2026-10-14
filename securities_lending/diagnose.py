"""Read environment metadata; only contact Wind when --wind is explicit."""
import argparse
import importlib.metadata
import json
import struct
import subprocess
import sys

from .config import ROOT, load_config, today
from .inventory import normalize_code
from .wind import IndustryProvider, wind_executable


def main():
    parser = argparse.ArgumentParser(description="检查券源 App Python / Wind 环境")
    parser.add_argument("--wind", metavar="CODE", help="连接 Wind 并试取一只证券的最新价与行业，例如 000001.SZ")
    args = parser.parse_args()
    config = load_config(ROOT / "config.local.json")
    packages = {}
    for name in ("PySide6-Essentials", "openpyxl", "xlrd"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "未安装"
    result = {"app_python": sys.executable, "python_version": sys.version,
              "architecture_bits": struct.calcsize("P") * 8, "packages": packages,
              "wind_python": wind_executable(config)}
    try:
        probe = subprocess.run([wind_executable(config), "-s", "-c", "import importlib.util; print(bool(importlib.util.find_spec('WindPy')))"],
                               capture_output=True, text=True, timeout=10,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        result["windpy_detected"] = probe.returncode == 0 and probe.stdout.strip() == "True"
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["windpy_detected"] = False
        result["wind_environment_error"] = str(exc)
    if args.wind:
        code = normalize_code(args.wind)
        if not code:
            parser.error("请提供有效的沪/深/北证券代码")
        provider = IndustryProvider(ROOT / "data" / "diagnostics")
        industries, quotes, warnings = provider.market([code], [code], today(), {**config, "wind_enabled": True})
        result["wind_check"] = {"industries": industries, "quotes": quotes, "warnings": warnings}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

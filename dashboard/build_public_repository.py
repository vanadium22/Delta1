"""Export shared market UI as an independent local Git repository.

Existing project history, calculation code, settings and accounts are excluded.
No remote is created or contacted. Rebuild after shared UI or protocol changes.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile
try:
    from .release_profiles import profile,ScopeCompiler,restrict_bundle,prune_imports
except ImportError:
    from release_profiles import profile,ScopeCompiler,restrict_bundle,prune_imports

ROOT = Path(__file__).resolve().parent
DEFAULT_REPOSITORY = ROOT / "runtime" / "distribution" / "Delta1-market-dashboard"
SHARED_FILES = ("bootstrap.py", "branding.py", "startup.py", "theme.py", "widgets.py",
                "instruments.py", "trading_axis.py", "market_view.py", "basis_panel.py", "public_app.py", "public_entry.py")
EXPORT_NAMES = {"public_app.py": "shell.py", "public_entry.py": "__main__.py"}
READ_PROTOCOL_NAMES = {"PRODUCTS", "FREQUENCIES", "SCHEMA", "DEFAULT_PUBLISH_ROOT", "FRAME_KEYS",
    "FRAME_COLUMNS", "STATE_KEYS", "utc_now", "view_key", "empty_state", "decode_state", "ViewerModel"}
FORBIDDEN_TEXT = re.compile(r"developer|viewer|edition|开发者|精简版|阉割|双版本|两版|formula_code|"
    r"CollectionJob|factor_worker|DeveloperModel|marketdata\.repository", re.IGNORECASE)
FORBIDDEN_FILES = {"app.py", "model.py", "developer_model.py", "metrics.py", "factors.py",
    "factor_worker.py", "collection.py", "demo.py", "dashboard_page.py"}
PUBLIC_MODULES = {Path(EXPORT_NAMES.get(name, name)).stem for name in SHARED_FILES} | {"publication","presentation"}


class PublicSource(ast.NodeTransformer):
    """Select display dependencies and normalize feed terminology."""
    def visit_Module(self, node):
        self.generic_visit(node)
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
            node.body.pop(0)
        return node

    def visit_Name(self, node):
        node.id = {"ViewerModel": "MarketFeed", "edition": "profile"}.get(node.id, node.id)
        return node

    def visit_arg(self, node):
        if node.arg == "edition": node.arg = "profile"
        return node

    def visit_keyword(self, node):
        self.generic_visit(node)
        if node.arg == "edition": node.arg = "profile"
        return node

    def visit_alias(self, node):
        if node.name == "ViewerModel": node.name = "MarketFeed"
        return node

    def visit_ImportFrom(self, node):
        self.generic_visit(node)
        if node.module == "public_app": node.module = "shell"
        return node

    def visit_ClassDef(self, node):
        if node.name == "ViewerModel":
            node.name = "MarketFeed"
            node.body = [item for item in node.body
                if not (isinstance(item, ast.FunctionDef) and item.name == "_deny")
                and not (isinstance(item, ast.Assign) and any(isinstance(target, ast.Name) and target.id in {
                    "edition", "save_config", "publish_formula", "preview", "archive", "result_history"
                } for target in item.targets))]
        elif node.name == "PythonHighlight": return None
        self.generic_visit(node)
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
            node.body.pop(0)
        return node

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            for old, new in (("等待开发者版发布指标", "等待市场数据更新"),
                ("请同步更新精简版程序", "请更新市场看板程序"),
                ("请由开发者检查", "请检查指标数据源"),
                ("developer", "market"), ("viewer", "market"),
                ("SWHY_DELTA1_PUBLISH_ROOT", "DELTA1_DATA_ROOT")):
                node.value = node.value.replace(old, new)
        return node


def public_python(name, *, reading_protocol=False,stage="100"):
    tree = ast.parse((ROOT / "native" / name).read_text(encoding="utf-8-sig"), filename=name)
    if reading_protocol:
        selected = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module in {"copy", "datetime", "pathlib","presentation"}: selected.append(node)
            elif isinstance(node, ast.Import):
                node.names = [alias for alias in node.names if alias.name in {"json", "math", "pandas"}]
                if node.names: selected.append(node)
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in READ_PROTOCOL_NAMES: selected.append(node)
            elif isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in READ_PROTOCOL_NAMES for target in node.targets): selected.append(node)
        tree.body = selected
    tree = PublicSource().visit(tree)
    tree = prune_imports(ScopeCompiler(profile(stage)).visit(tree))
    if name=="public_entry.py":
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=="add_argument" and node.args and isinstance(node.args[0],ast.Constant) and node.args[0].value=="--capture-page":
                for keyword in node.keywords:
                    if keyword.arg=="choices": keyword.value=ast.parse(repr(tuple(range(len(profile(stage)["MODULE_TITLES"])))) ,mode="eval").body
    ast.fix_missing_locations(tree)
    return (ast.unparse(tree) + "\n").encode("utf-8")


def _readme(stage="100"):
    text="""# Delta1 市场看板

石墨金主题的 Windows 桌面市场观察工具，包含三个页面：

- 股指期货：IF、IH、IC、IM 的可比指标、期限结构与回归结果。
- 特殊指标：期现、跨期、跨品种计算结果及自定义指标。
- 市场异动：按偏离程度与数据时刻查看异常事件及依据。

## 运行

需要 Python 3.12–3.14，当前使用 Python 3.13 验证。安装依赖后启动：

```powershell
python -m pip install -r requirements.txt
python -B -s -X utf8 -m dashboard
```

Windows 也可以双击 `start_app.cmd`。若 Python 不在 PATH 中，将
`DELTA1_PYTHON` 设置为该环境的 python.exe。
运行 `create_shortcut.ps1` 可在仓库目录创建带应用图标的 `Delta1.lnk`。

通过 `--publish-root` 或 `DELTA1_DATA_ROOT` 指定快照目录：

```powershell
python -m dashboard --publish-root "Z:\\MarketData\\Delta1"
```

快照目录的 `current.json` 保存市场数据。没有输入时页面显示待接入，
快照过期时保留最后结果并标记过期；程序不会把旧行情当作实时行情。

`--demo` 显示合成示例，只读取 `demo.json`。示例不代表真实市场行情。
若仓库包含 `dashboard/data/demo.json`，可直接运行：

```powershell
python -m dashboard --demo
```

Windows 也可以双击 `start_demo.cmd` 查看示例。

程序只消费展示所需的快照，不要求安装行情账号或交易接口。
指标中的成本、回归或偏离值需要结合其口径和数据质量判断。
程序版本和文件校验信息保存在 `release.json`。

## 更新

使用 `git pull` 获取已发布代码，再按需安装更新后的依赖并重启。
运行目录、日志、真实数据和本机环境不会纳入 Git。
"""
    settings=profile(stage)
    intro="石墨金主题的 Windows 桌面市场观察工具。当前交付："+settings["RELEASE_NAME"]+"。\n\n"
    intro+="\n".join("- "+title for title in settings["MODULE_TITLES"])+"\n\n"
    text=text[:text.index("石墨金")]+intro+text[text.index("## 运行"):]
    text+="\n图表仅展示交易时段，午休、隔夜及非交易日折叠，缺失行情保留断线。\n"
    if not settings["AUTO_REFRESH"]: text+="本稿使用手动刷新。\n"
    return text.encode("utf-8")


def source_files(*, demo_path=None,stage="100"):
    if str(stage)=="20": raise ValueError("The indicator sample is exported as an Excel workbook")
    settings=profile(stage)
    files = {
        "dashboard/__init__.py": b"",
        "dashboard/__main__.py": b"from .native.__main__ import main\n\nraise SystemExit(main())\n",
        "dashboard/native/__init__.py": b"",
        "README.md": _readme(stage),
        ".gitignore": b"__pycache__/\n*.py[cod]\n.venv/\nruntime/\ndashboard/runtime/\ndashboard/localsetting/\n*.log\n*.lnk\n",
        "requirements.txt": ("PySide6-Essentials==6.11.2\nshiboken6==6.11.2\npyqtgraph==0.14.0\n"
            "numpy==2.5.3\npandas==3.0.3\ntzdata==2026.4\n").encode(),
        "start_app.cmd": ('@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\n'
            'set "DELTA1_APP_PYTHON=python"\r\n'
            'if defined DELTA1_PYTHON set "DELTA1_APP_PYTHON=%DELTA1_PYTHON%"\r\n'
            '"%DELTA1_APP_PYTHON%" -B -s -X utf8 -m dashboard %*\r\n'
            'if errorlevel 1 pause\r\n').encode(),
        "start_demo.cmd": b'@echo off\r\ncall "%~dp0start_app.cmd" --demo %*\r\n',
        "create_shortcut.ps1": ("$ErrorActionPreference = 'Stop'\n"
            "$appRoot = $PSScriptRoot\n"
            "$shell = New-Object -ComObject WScript.Shell\n"
            "$shortcut = $shell.CreateShortcut((Join-Path $appRoot 'Delta1.lnk'))\n"
            "$shortcut.TargetPath = Join-Path $appRoot 'start_app.cmd'\n"
            "$shortcut.WorkingDirectory = $appRoot\n"
            "$shortcut.IconLocation = (Join-Path $appRoot 'dashboard/assets/delta1.ico') + ',0'\n"
            "$shortcut.Description = 'Delta1 Market Dashboard'\n"
            "$shortcut.Save()\n").encode(),
    }
    for name in SHARED_FILES:
        if name=="basis_panel.py" and not settings["SHOW_DETAIL"]: continue
        files["dashboard/native/" + EXPORT_NAMES.get(name, name)] = public_python(name,stage=stage)
    files["dashboard/native/publication.py"] = public_python("publication.py", reading_protocol=True,stage=stage)
    used=set()
    for name,value in files.items():
        if name.endswith(".py"):
            for node in ast.walk(ast.parse(value)):
                if isinstance(node,ast.ImportFrom) and node.module=="presentation": used.update(a.name for a in node.names)
    files["dashboard/native/presentation.py"]=("\n".join(f"{key} = {settings[key]!r}" for key in sorted(used))+"\n").encode("utf-8")
    for name in ("delta1.svg", "delta1.png", "delta1.ico", "research.svg", "research.png", "research.ico"):
        files["dashboard/assets/" + name] = (ROOT / "assets" / name).read_bytes()
    if demo_path:
        if str(ROOT.parent) not in sys.path: sys.path.insert(0,str(ROOT.parent))
        demo = json.loads(Path(demo_path).read_text(encoding="utf-8"))
        if demo.get("demo") is not True:
            raise ValueError("Only explicitly synthetic data may be embedded in the source repository")
        spec = importlib.util.spec_from_file_location("dashboard.native._export_protocol", ROOT / "native" / "publication.py")
        protocol = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(protocol)
        if demo.get("schema_version") != protocol.SCHEMA:
            raise ValueError("Synthetic snapshot schema does not match the current display protocol")
        sanitized = {key: demo[key] for key in ("schema_version", "snapshot_id", "generated_at", "heartbeat_at", "demo")}
        sanitized["views"] = {}
        for key, value in demo["views"].items():
            state = protocol.decode_state(value)
            if state["demo"] is not True:
                raise ValueError("Every embedded demo view must be synthetic")
            sanitized["views"][key] = protocol.encode_state(state)
        demo = restrict_bundle(sanitized,stage)
        files["dashboard/data/demo.json"] = json.dumps(demo, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    audit_files(files)
    hashes = {name: hashlib.sha256(value).hexdigest() for name, value in sorted(files.items())}
    build_id = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:12]
    files["release.json"] = json.dumps({"application": "Delta1 市场看板", "build_id": build_id,
        "format": 1, "release_name":settings["RELEASE_NAME"], "files": hashes}, ensure_ascii=False, indent=2).encode("utf-8")
    return files, build_id


def audit_files(files):
    for name, value in files.items():
        if Path(name).name in FORBIDDEN_FILES:
            raise ValueError(f"Private module is forbidden in the public repository: {name}")
        if Path(name).suffix.lower() in {".py", ".md", ".txt", ".json", ".cmd", ".svg", ".ps1"}:
            content = value.decode("utf-8-sig")
            found = FORBIDDEN_TEXT.search(content)
            if found: raise ValueError(f"Private terminology in {name}: {found.group(0)}")
            if re.search(r"[PT]:[\\/]", content): raise ValueError(f"Local workspace path is forbidden in {name}")
        if name.endswith(".py"):
            tree = ast.parse(value, filename=name)
            compile(tree, name, "exec")
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level and node.module and node.module.split(".")[0] not in PUBLIC_MODULES | {"native"}:
                    raise ValueError(f"Unexpected public dependency {node.module} in {name}")


def build_archive(destination=None, *, demo_path=None,stage="100"):
    files, build_id = source_files(demo_path=demo_path,stage=stage)
    target = Path(destination or ROOT / "runtime" / "distribution" / f"Delta1-market-dashboard-{build_id}.zip").resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in sorted(files.items()): archive.writestr(name, value)
    return target


def _git(target, *args):
    return subprocess.run(["git", "-c", "core.hooksPath=.git/empty-hooks", "-c", "commit.gpgsign=false",
        "-C", str(target), *args], check=True, capture_output=True, text=True, encoding="utf-8")


def build_repository(destination=None, *, demo_path=None, commit=True,stage="100"):
    files, build_id = source_files(demo_path=demo_path,stage=stage)
    suffix={"50":"Delta1-market-prototype","80":"Delta1-market-integration","100":"Delta1-market-dashboard"}[str(stage)]
    target = Path(destination or DEFAULT_REPOSITORY.parent/suffix).resolve()
    if target == ROOT or ROOT in target.parents and not (ROOT / "runtime" / "distribution") in target.parents:
        raise ValueError("Generated repositories inside the project must stay under runtime/distribution")
    if target.is_symlink(): raise ValueError("A repository destination cannot be a symbolic link")
    previous = {}
    if target.exists() and any(target.iterdir()):
        receipt = target / "release.json"
        if not receipt.is_file() or not (target / ".git").is_dir():
            raise ValueError("An existing non-generated directory cannot be replaced")
        prior_release=json.loads(receipt.read_text(encoding="utf-8"))
        if prior_release.get("release_name","1.0")!=profile(stage)["RELEASE_NAME"]:
            raise ValueError("Each delivery scope needs its own Git history; use a different directory")
        previous = prior_release.get("files", {})
        allowed = set(previous) | {"release.json"}
        recorded = set(_git(target, "ls-files").stdout.splitlines())
        staged = set(_git(target, "diff", "--cached", "--name-only").stdout.splitlines())
        if (recorded | staged) - allowed:
            raise ValueError("The generated repository contains additional tracked or staged files; export to a new directory")
        for name, expected in previous.items():
            path = target / name
            if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"Generated public file was modified locally; preserve it before updating: {name}")
    target.mkdir(parents=True, exist_ok=True)
    for name in previous.keys() - files.keys():
        path = (target / name).resolve()
        if target not in path.parents: raise ValueError("Manifest file escaped the generated repository")
        path.unlink()
    for name, value in files.items():
        path = target / name
        if target not in path.resolve().parents: raise ValueError("Exported file escaped the generated repository")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    if not (target / ".git").exists(): _git(target, "init", "--initial-branch=main")
    top = Path(_git(target, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    if top != target: raise ValueError("Generated Git repository does not own its destination")
    if _git(target, "symbolic-ref", "--short", "HEAD").stdout.strip() != "main":
        raise ValueError("Generated public releases must use the independent main branch")
    _git(target, "add", "--all", "--", *sorted(set(previous) | set(files)))
    if commit and _git(target, "diff", "--cached", "--name-only").stdout.strip():
        _git(target, "-c", "user.name=Delta1 Releases", "-c", "user.email=release@delta1.local",
            "commit", "--no-gpg-sign", "-m", f"Release {build_id}")
    return target


def export_git_bundle(repository, destination=None):
    """Audit every public revision, then create a self-contained offline Git file."""
    target = Path(repository).resolve()
    receipt = json.loads((target / "release.json").read_text(encoding="utf-8"))
    if receipt.get("application") != "Delta1 市场看板":
        raise ValueError("Bundle export requires the generated public repository")
    if _git(target, "diff", "--cached", "--name-only").stdout.strip() or _git(target, "diff", "--name-only").stdout.strip():
        raise ValueError("Commit the public export before creating an offline Git bundle")
    commits = _git(target, "rev-list", "main").stdout.splitlines()
    if not commits:
        raise ValueError("Commit a public release before creating an offline Git bundle")
    for commit in commits:
        files = {}
        paths = _git(target, "ls-tree", "-r", "--name-only", commit).stdout.splitlines()
        for name in paths:
            if Path(name).name in FORBIDDEN_FILES:
                raise ValueError(f"Private module appears in public Git history: {name}")
            if Path(name).suffix.lower() in {".py", ".md", ".txt", ".json", ".cmd", ".svg", ".ps1"}:
                result = subprocess.run(["git", "-C", str(target), "show", f"{commit}:{name}"],
                                        check=True, capture_output=True)
                files[name] = result.stdout
        audit_files(files)
    messages = _git(target, "log", "--format=%B", "main").stdout
    if FORBIDDEN_TEXT.search(messages):
        raise ValueError("Private terminology appears in public commit messages")
    output = Path(destination or target.parent / f"Delta1-market-dashboard-{receipt['build_id']}.bundle").resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    _git(target, "bundle", "create", str(output), "HEAD", "main")
    _git(target, "bundle", "verify", str(output))
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="Independent source Git repository directory")
    parser.add_argument("--stage",choices=("50","80","100"),default="100",help="Internal delivery scope")
    parser.add_argument("--demo-file", help="Optional, explicitly synthetic demo.json")
    parser.add_argument("--no-commit", action="store_true")
    parser.add_argument("--archive", help="Also save a portable source ZIP to this path")
    parser.add_argument("--bundle", nargs="?", const="", help="Also create an offline Git bundle; optional output path")
    args = parser.parse_args(argv)
    repository = build_repository(args.output, demo_path=args.demo_file, commit=not args.no_commit,stage=args.stage)
    result = {"repository": str(repository)}
    if args.archive: result["archive"] = str(build_archive(args.archive, demo_path=args.demo_file,stage=args.stage))
    if args.bundle is not None: result["bundle"] = str(export_git_bundle(repository, args.bundle or None))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__": main()

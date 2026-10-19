"""A bounded expression-oriented Python worker; no imports or arbitrary calls.

Runs in a short-lived child process. This is a deliberately limited language,
not a general-purpose Python sandbox. Only the local authenticated UI publishes it.
"""
from __future__ import annotations

import ast
import json
import math
import operator
import statistics
import sys

ALLOWED = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Assign,
           ast.Name, ast.Load, ast.Store, ast.Constant, ast.Dict, ast.List, ast.Tuple,
           ast.Subscript, ast.Slice, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult,
           ast.Div, ast.FloorDiv, ast.Mod, ast.USub, ast.UAdd, ast.If, ast.IfExp,
           ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is,
           ast.IsNot, ast.BoolOp, ast.And, ast.Or, ast.Not, ast.Call, ast.keyword)


def sma(rows, field, window):
    if type(window) is not int or not 1 <= window <= 300:
        raise ValueError("window 必须为 1–300 的整数")
    values = [row.get(field) for row in rows[-window:]]
    if len(values) < window or any(v is None for v in values):
        return None
    return statistics.mean(values)


HELPERS = {"abs": abs, "min": min, "max": max, "round": round, "sum": sum,
           "len": len, "mean": statistics.mean, "stdev": statistics.stdev,
           "sqrt": math.sqrt, "log": math.log, "sma": sma}

ARITHMETIC = {"Add": operator.add, "Sub": operator.sub, "Mult": operator.mul,
              "Div": operator.truediv, "FloorDiv": operator.floordiv, "Mod": operator.mod}


def bounded_arithmetic(operation, left, right):
    if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e100 for v in (left, right)):
        raise ValueError("四则运算只接受有限数值；不支持字符串或列表扩增")
    result = ARITHMETIC[operation](left, right)
    if not math.isfinite(result) or abs(result) > 1e100:
        raise ValueError("中间计算值过大")
    return result


class NumericOperations(ast.NodeTransformer):
    def visit_BinOp(self, node):
        self.generic_visit(node)
        return ast.copy_location(ast.Call(func=ast.Name(id="_arithmetic", ctx=ast.Load()),
            args=[ast.Constant(type(node.op).__name__), node.left, node.right], keywords=[]), node)


def validate(code, *, api="v1", helpers=None):
    if not isinstance(code, str) or not 1 <= len(code) <= 12000:
        raise ValueError("代码需要 1–12000 个字符")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"第 {exc.lineno} 行：{exc.msg}") from None
    signature = ["inputs","params"] if api=="v2" else ["quotes","history","params"]
    helper_names = set(HELPERS if helpers is None else helpers)
    message = "compute("+", ".join(signature)+")"
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("只允许一个 "+message+" 函数")
    fn = tree.body[0]
    if (fn.name != "compute" or [a.arg for a in fn.args.args] != signature
            or fn.decorator_list or fn.args.defaults or fn.args.kwonlyargs or fn.args.posonlyargs
            or fn.args.vararg or fn.args.kwarg or fn.returns):
        raise ValueError("函数签名必须是 "+message)
    nodes = list(ast.walk(tree))
    if len(nodes) > 1000:
        raise ValueError("公式过长")
    for node in nodes:
        if not isinstance(node, ALLOWED):
            raise ValueError(f"模板不支持 {type(node).__name__}；不支持 import、属性访问、循环或文件操作")
        if isinstance(node, ast.FunctionDef) and node is not fn:
            raise ValueError("不支持嵌套函数")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError("不支持以下划线开头的名称")
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in helper_names):
            raise ValueError("可调用函数：" + ", ".join(sorted(helper_names)))
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name) or target.id in helper_names | set(signature):
                    raise ValueError("仅允许给新的局部变量赋值")
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (str, bytes)) and len(node.value) > 200:
                raise ValueError("字符串常量过长")
            if isinstance(node.value, int) and abs(node.value) > 10**12:
                raise ValueError("整数常量过大")
    return tree


def run(payload):
    tree = validate(payload["code"])
    tree = ast.fix_missing_locations(NumericOperations().visit(tree))
    namespace = {"__builtins__": {}, **HELPERS, "_arithmetic": bounded_arithmetic}
    exec(compile(tree, "<formula>", "exec"), namespace)
    values = namespace["compute"](payload["quotes"], payload["history"], payload["params"])
    if not isinstance(values, dict) or not 1 <= len(values) <= 20:
        raise ValueError("输出必须为包含 1–20 个指标的 dict")
    for key, value in values.items():
        if not isinstance(key, str) or not 1 <= len(key) <= 60:
            raise ValueError("指标名称需要 1–60 个字符")
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e15):
            raise ValueError("指标值必须为有限数字或 None，且绝对值不超过 1e15")
    return values


if __name__ == "__main__":
    try:
        payload = json.loads(sys.stdin.buffer.read(2_000_001))
        result = {"values": run(payload)}
    except Exception as exc:
        result = {"error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8"))

"""Isolated process: Wind cannot hold up inventory lookup indefinitely."""
import contextlib
import json
import sys


def fetch(request, w):
    status = w.start(waitTime=10, showmenu=False)
    if status.ErrorCode != 0:
        raise RuntimeError(f"Wind 连接失败：{status.ErrorCode}")
    result = {}
    for start in range(0, len(request["codes"]), 100):
        batch = request["codes"][start:start + 100]
        response = w.wss(",".join(batch), request["field"], request["options"])
        if response.ErrorCode != 0:
            raise RuntimeError(f"Wind 查询失败：{response.ErrorCode}，请用终端代码生成器核对行业字段与权限")
        if not response.Data or len(response.Data[0]) != len(response.Codes):
            raise RuntimeError("Wind 返回的行业数据长度不一致")
        for code, value in zip(response.Codes, response.Data[0]):
            if isinstance(value, str) and value.strip() and value.strip().casefold() not in {"nan", "none", "null", "n/a", "--"}:
                result[code.upper()] = value.strip()
    return result


def main():
    request = json.loads(sys.stdin.read())
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from WindPy import w
            result = fetch(request, w)
        output = {"industries": result, "error": None}
    except Exception as exc:
        output = {"industries": {}, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(output, ensure_ascii=True))


if __name__ == "__main__":
    main()

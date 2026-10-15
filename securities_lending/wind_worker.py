"""Isolated process: Wind cannot hold up inventory lookup indefinitely."""
import contextlib
import json
import math
import re
import sys
from datetime import datetime, timedelta, timezone


def valid_name(value):
    return isinstance(value, str) and value.strip().casefold() not in {"", "nan", "none", "null", "n/a", "--"}


def fetch_securities(request, w):
    status = w.start(waitTime=10, showmenu=False)
    if status.ErrorCode != 0:
        raise RuntimeError(f"Wind 连接失败：{status.ErrorCode}")
    securities, warnings = {}, []
    codes = request.get("codes", [])
    for start in range(0, len(codes), 100):
        batch = codes[start:start + 100]
        try:
            response = w.wss(",".join(batch), "sec_name", "")
            if response.ErrorCode != 0:
                raise ValueError(f"Wind 名称查询失败：{response.ErrorCode}")
            if not response.Data or len(response.Data[0]) != len(response.Codes):
                raise ValueError("Wind 名称返回长度不一致")
            for code, name in zip(response.Codes, response.Data[0]):
                code = str(code).upper()
                if code in batch and valid_name(name):
                    securities[code] = {"name": name.strip(), "source": "Wind WSS · SEC_NAME"}
        except Exception as exc:
            warnings.append(str(exc))
    if request.get("names"):
        try:
            # Name lookup is limited to the current A-share universe. No result
            # is inconclusive for ETFs, delisted stocks, aliases and other markets.
            response = w.wset("sectorconstituent", f"date={request['day']};sector=全部A股")
            if response.ErrorCode != 0:
                raise ValueError(f"Wind A股名称检索失败：{response.ErrorCode}")
            fields = [str(field).lower() for field in response.Fields]
            code_values = response.Data[fields.index("wind_code")]
            names = response.Data[fields.index("sec_name")]
            if len(code_values) != len(names):
                raise ValueError("Wind A股代码与名称长度不一致")
            pairs = [(str(code).upper(), name.strip()) for code, name in zip(code_values, names)
                     if valid_name(name) and re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", str(code).upper())]
            for token in request["names"]:
                exact = [(code, name) for code, name in pairs if name.casefold() == token.casefold()]
                matches = exact or [(code, name) for code, name in pairs if token.casefold() in name.casefold()]
                if len(matches) > 100:
                    warnings.append(f"名称「{token}」匹配超过100只，请输入完整名称或代码")
                    continue
                for code, name in matches:
                    securities[code] = {"name": name, "source": "Wind WSET · 全部A股"}
        except Exception as exc:
            warnings.append(str(exc))
    return {"securities": securities, "warnings": warnings, "error": None}


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


def fetch_market(request, w):
    status = w.start(waitTime=10, showmenu=False)
    if status.ErrorCode != 0:
        raise RuntimeError(f"Wind 连接失败：{status.ErrorCode}")
    quotes, industries, warnings = {}, {}, []
    for start in range(0, len(request["quote_codes"]), 100):
        batch = request["quote_codes"][start:start + 100]
        try:
            response = w.wsq(",".join(batch), "rt_last")
            if response.ErrorCode != 0:
                raise RuntimeError(f"Wind 最新价查询失败：{response.ErrorCode}")
            fields = [str(field).upper() for field in response.Fields]
            if "RT_LAST" not in fields:
                raise ValueError("Wind 返回缺少 RT_LAST 字段")
            values = response.Data[fields.index("RT_LAST")]
            if len(values) != len(response.Codes):
                raise ValueError("Wind 最新价数据长度不一致")
            retrieved = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
            times = getattr(response, "Times", [])
            for index, (code, value) in enumerate(zip(response.Codes, values)):
                code = str(code).upper()
                try:
                    valid = not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0
                except (TypeError, ValueError, OverflowError):
                    valid = False
                if code not in batch or not valid:
                    continue
                wind_time = times[index] if len(times) == len(response.Codes) else times[0] if len(times) == 1 else None
                quotes[code] = {"price": str(value), "retrieved_at": retrieved,
                                "wind_returned_at": str(wind_time) if wind_time is not None else None,
                                "source": "Wind WSQ · RT_LAST"}
        except Exception as exc:
            warnings.append(str(exc))
    missing = sorted(set(request["quote_codes"]) - quotes.keys())
    if missing:
        warnings.append("未返回有效最新价：" + ", ".join(missing))
    for start in range(0, len(request["industry_codes"]), 100):
        batch = request["industry_codes"][start:start + 100]
        try:
            response = w.wss(",".join(batch), request["field"], request["options"])
            if response.ErrorCode != 0:
                raise RuntimeError(f"Wind 行业查询失败：{response.ErrorCode}；最新价结果保留")
            if not response.Data or len(response.Data[0]) != len(response.Codes):
                raise ValueError("Wind 行业数据长度不一致")
            for code, value in zip(response.Codes, response.Data[0]):
                if str(code).upper() in batch and isinstance(value, str) and value.strip().casefold() not in {"", "nan", "none", "null", "n/a", "--"}:
                    industries[str(code).upper()] = value.strip()
        except Exception as exc:
            warnings.append(str(exc))
    return {"quotes": quotes, "industries": industries, "warnings": warnings, "error": None}


def main():
    request = json.loads(sys.stdin.read())
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from WindPy import w
            if request.get("operation") == "resolve":
                output = fetch_securities(request, w)
            elif request.get("operation") == "market":
                output = fetch_market(request, w)
            else:
                output = {"industries": fetch(request, w), "error": None}
    except Exception as exc:
        output = {"industries": {}, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(output, ensure_ascii=True))


if __name__ == "__main__":
    main()

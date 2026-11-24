"""Single bounded, read-only WSD request using the configured Wind terminal."""
from contextlib import redirect_stdout
import json
from pathlib import Path
import subprocess
import sys


WIND_CLOSE = 'Wind 盘后收盘'
WIND_LOCAL_CLOSE = 'Wind 本地收盘'


def download_closes(codes, day, config, profile):
    from dashboard.marketdata.overview_windpy import executable
    from dashboard.python_environment import child_environment

    python = executable(config, profile)
    command = [python, '-B', '-X', 'utf8', '-m', 'basis_trade_ledger.wind_close']
    try:
        process = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=child_environment(python),
            input=json.dumps(dict(day=day, codes=codes)), capture_output=True, text=True, encoding='utf-8',
            timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True)
        response = json.loads(process.stdout)
    except subprocess.TimeoutExpired:
        return {}, 'Wind 盘后查询超时'
    except (OSError, ValueError, subprocess.CalledProcessError):
        return {}, 'Wind 盘后进程未完成查询'
    if not isinstance(response, dict):
        return {}, 'Wind 盘后进程返回无效结果'
    if response.get('error') == 'missing_sdk':
        return {}, 'Wind Python 缺少 WindPy'
    if response.get('error') or response.get('day') != day or not isinstance(response.get('prices'), dict):
        return {}, 'Wind 盘后收盘价未取得'
    return response['prices'], ''


def main():
    from dashboard.marketdata.wind_terminal_worker import checked, daily
    from index_strategy.instant_dld.quotes import price_number

    request = json.load(sys.stdin)
    wind = None
    try:
        with redirect_stdout(sys.stderr):
            from WindPy import w as wind
            checked(wind.start(waitTime=10, showmenu=False), 'Wind 连接')
            values = daily(wind, request['codes'], 'close', request['day'], 'PriceAdj=U;Period=D')
        response = dict(day=request['day'], prices={symbol: price for symbol, value in values.items()
                                                    if (price := price_number(value)) is not None})
    except ModuleNotFoundError as exc:
        response = dict(error='missing_sdk' if exc.name == 'WindPy' else 'sdk_dependency')
    except Exception:
        response = dict(error='wind_request')
    finally:
        if wind is not None:
            try:
                with redirect_stdout(sys.stderr):
                    wind.stop()
            except Exception:
                pass
    print(json.dumps(response, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()

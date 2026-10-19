"""Bounded diagnostic Wind worker; never returns prices or account information."""
import importlib
import struct
import sys

if __package__:
    from .wind_worker import CALENDAR_OPTIONS, json_safe, main, perform as normal_perform
else:
    from wind_worker import CALENDAR_OPTIONS, json_safe, main, perform as normal_perform


def snapshot(result):
    data = getattr(result, "Data", None)
    times = getattr(result, "Times", [])
    columns = data if isinstance(data, (list, tuple)) else []
    return json_safe({
        "error_code": getattr(result, "ErrorCode", None),
        "state_code": getattr(result, "StateCode", None),
        "fields": list(getattr(result, "Fields", []))[:8],
        "codes_count": len(getattr(result, "Codes", [])),
        "times_count": len(times) if isinstance(times, (list, tuple)) else None,
        "times_sample": list(times[:3]) if isinstance(times, (list, tuple)) else [],
        "data_columns": len(columns) if isinstance(data, (list, tuple)) else None,
        "data_lengths": [len(c) if isinstance(c, (list, tuple)) else type(c).__name__ for c in columns[:4]],
        "data_sample": [[str(v)[:160] if not isinstance(v, (int, float)) else v for v in c[:3]]
                       if isinstance(c, (list, tuple)) else str(c)[:160] for c in columns[:4]],
    })


def perform(w, request):
    op = request["operation"]
    if op == "diagnostic_environment":
        module = importlib.import_module("WindPy")
        return {"python": sys.executable, "python_version": sys.version.split()[0],
                "bits": struct.calcsize("P") * 8, "windpy_file": getattr(module, "__file__", None),
                "connected": bool(w.isconnected()) if hasattr(w, "isconnected") else None}
    if op == "diagnostic_calendar":
        response = {"start": request["start"], "end": request["end"], "options": CALENDAR_OPTIONS}
        for api in ("tdays", "tdayscount"):
            try:
                response[api] = snapshot(getattr(w, api)(request["start"], request["end"], CALENDAR_OPTIONS))
            except Exception as exc:
                response[api] = {"exception": f"{type(exc).__name__}: {exc}"[:2000]}
        return response
    return normal_perform(w, request)


if __name__ == "__main__":
    main(perform)

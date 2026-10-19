"""Bounded diagnostic Wind worker; never returns prices or account information."""
import importlib
import struct
import sys

if __package__:
    from .wind_worker import CALENDAR_OPTIONS, calendar, json_safe, main, perform as normal_perform
else:
    from wind_worker import CALENDAR_OPTIONS, calendar, json_safe, main, perform as normal_perform


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
        attempts = []
        try:
            response["days"] = calendar(w, request["start"], request["end"], attempts)
        except Exception as exc:
            response["error"] = f"{type(exc).__name__}: {exc}"[:3000]
        response["attempts"] = [
            {key: snapshot(value) if key in ("tdays", "tdayscount") else value for key, value in item.items()}
            for item in attempts]
        selected = next((item for item in response["attempts"] if item.get("selected")), None)
        if selected:
            response.update(options=selected["options"], date_format=selected["date_format"],
                            tdays=selected["tdays"], tdayscount=selected["tdayscount"])
        elif request.get("controls"):
            # Equity/default and calendar-day controls are evidence only. They
            # must never become the futures calendar used for data writes.
            response["controls"] = []
            for options, style in (("", "iso"), ("TradingCalendar=SSE;Days=Trading", "compact"),
                                   ("Days=Alldays", "compact")):
                first, last = request["start"], request["end"]
                if style == "compact":
                    first, last = first.replace("-", ""), last.replace("-", "")
                item = {"options": options, "date_format": style, "sent_start": first, "sent_end": last}
                response["controls"].append(item)
                for api in ("tdays", "tdayscount"):
                    try:
                        item[api] = snapshot(getattr(w, api)(first, last, options))
                    except Exception as exc:
                        item[api] = {"exception": f"{type(exc).__name__}: {exc}"[:2000]}
        return response
    return normal_perform(w, request)


if __name__ == "__main__":
    main(perform)

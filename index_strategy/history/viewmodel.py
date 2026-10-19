"""Request-scoped presentation state, independent from Tk and database connections."""
from collections import OrderedDict

STATES = {"running": "正在处理", "complete": "下载完成", "preview": "预览完成", "partial": "部分完成",
          "failed": "请求失败", "cancelled": "已停止", "empty": "没有可用数据"}
ORIGINS = {"native": "原始", "derived": "其他频率生成", "mixed": "原始 + 补齐",
           "derivable": "可生成 · 待校验", "unavailable": "无记录", "mapping_missing": "映射缺失",
           "pending": "当日待完成", "failed": "失败"}


class RequestView:
    def __init__(self, request_id, request=None, started_at=""):
        self.request_id, self.request, self.started_at = request_id, request or {}, started_at
        self.state = "running"
        self.plan, self.blocks, self.metadata = OrderedDict(), OrderedDict(), OrderedDict()
        self.logs, self.done = [], {}
        self.current = self.total = 0
        self.message = "正在连接内网数据源…"
        self.revision = 0

    @staticmethod
    def key(symbol, day):
        return f"{symbol}|{day}"

    def apply(self, event):
        self.revision += 1
        kind = event.get("type")
        stamp = event.get("event_time", "")[11:19]
        message, level = "", "信息"
        if kind == "request":
            self.request, self.started_at = event["request"], event.get("started_at", "")
            message = "新请求 · " + " / ".join([self.request.get("frequency", ""), self.request.get("start", ""), self.request.get("end", "")])
        elif kind == "coverage":
            self.plan = OrderedDict((self.key(x["symbol"], x["date"]), dict(x)) for x in event["items"])
            self.total = event["requested_items"]
            message = f"覆盖检查：{self.total} 个标的/交易日；排除 {event.get('nontrading_days', 0)} 个非交易日"
        elif kind == "item_status":
            item = event["item"]
            self.plan[self.key(item["symbol"], item["date"])] = dict(item)
        elif kind == "progress":
            self.current, self.total = event.get("current", 0), event.get("total", self.total)
            self.message = event["message"]
        elif kind in {"saved", "preview"}:
            meta = event["metadata"]
            key = self.key(meta["symbol"], meta["trading_date"])
            self.metadata[key] = meta
            self.blocks[key] = event.get("rows", [])
            message = f"{meta['symbol']} → {meta['source_symbol']} · {meta['trading_date']} · {meta['rows']} 行 · {ORIGINS.get(meta.get('origin'), '原始')}"
            if meta.get("quality") == "partial":
                level = "缺失"
                message += " · 空值字段：" + ", ".join(meta.get("missing_fields", []))
            if meta.get("warnings"):
                message += " · " + "；".join(meta["warnings"])
        elif kind == "error":
            level, message = "失败", f"{event.get('symbol', '')} {event.get('date', '')} {event['error']}".strip()
        elif kind == "log":
            message = event.get("message", "")
        elif kind == "done":
            self.done, self.state = event, event["state"]
            message = f"{STATES.get(self.state, self.state)} · {event.get('files', 0)} 文件 · {event.get('elapsed_seconds', 0):.2f} 秒"
        if message:
            self.logs.append(f"{stamp}  [{level}]  {message}")
            self.logs = self.logs[-1500:]

    @property
    def rows(self):
        rows = []
        for block in self.blocks.values():
            rows.extend(block[:max(0, 10000 - len(rows))])
        return rows

    @property
    def total_rows(self):
        return sum(meta["rows"] for meta in self.metadata.values())

    def coverage_rows(self):
        return [{"symbol": x["symbol"], "trading_date": x["date"], "source_symbol": x["source_symbol"],
                 "status": ORIGINS.get(x["status"], x["status"]) + (" · 待校验" if x["status"] == "native" and not x.get("sampled") else ""),
                 "quality": x.get("quality", "未抽样"), "rows": x.get("rows"), "reason": x["reason"],
                 "mapping_date": x.get("identity", {}).get("mapping_date"),
                 "mapping_rule": x.get("identity", {}).get("mapping_rule")}
                for x in self.plan.values()]

    def file_rows(self):
        return [{"symbol": m["symbol"], "trading_date": m["trading_date"], "source_symbol": m["source_symbol"],
                 "data_origin": m.get("origin"), "quality": m.get("quality"), "rows": m["rows"],
                 "seconds": m.get("total_seconds", m.get("query_seconds", 0)), "source": m.get("source"),
                 "file": m.get("file", "预览 · 未保存"), "mapping_rule": m["identity"]["mapping_rule"]}
                for m in self.metadata.values()]

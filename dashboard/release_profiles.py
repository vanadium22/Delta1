"""Internal delivery scopes. This module is never exported."""
import ast
from copy import deepcopy
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def profile(stage="100"):
    if str(stage) not in {"20","50","80","100"}: raise ValueError("Unknown delivery scope")
    tree=ast.parse((ROOT/"native/presentation.py").read_text(encoding="utf-8"))
    values={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)}
    if str(stage)=="50":
        values.update(RELEASE_NAME="桌面原型",MODULE_TITLES=("股指期货概览",),
            FREQUENCY_OPTIONS=(("1m","分钟"),),SHOW_SPECIAL=False,SHOW_EVENTS=False,
            SHOW_DETAIL=False,SHOW_EVENT_DETAIL=False,AUTO_REFRESH=False,
            FRAME_NAMES=("spread","basis","near","far","spot"),VALUE_NAMES=("spread","basis_bp"),ANALYTIC_NAMES=("calendar_bp",),
            MATRIX_TITLE="四品种基础指标",OVERVIEW_TEXT="IF / IH / IC / IM · 价格与价差观察",
            METRIC_ROWS=(("近月价格","near_price","点"),("现货指数","spot_price","点"),
                ("期现基差","basis_bp","bp"),("近月 − 远月","spread","点"),("标准化跨期价差","calendar_bp","bp")),
            CHART_OPTIONS=values["CHART_OPTIONS"][:2])
    elif str(stage)=="80":
        values.update(RELEASE_NAME="联调稿",FREQUENCY_OPTIONS=values["FREQUENCY_OPTIONS"][:2],
            SHOW_DETAIL=False,SHOW_EVENT_DETAIL=False,AUTO_REFRESH=False,
            FRAME_NAMES=("spread","basis","near","far","spot"),
            CHART_OPTIONS=values["CHART_OPTIONS"][:3])
    elif str(stage)=="20":
        values.update(RELEASE_NAME="指标样稿")
    return values


class ScopeCompiler(ast.NodeTransformer):
    def __init__(self,settings): self.settings=settings

    def visit_ImportFrom(self,node):
        if node.module=="basis_panel" and not self.settings["SHOW_DETAIL"]: return None
        return self.generic_visit(node)

    def visit_If(self,node):
        if isinstance(node.test,ast.Name) and isinstance(self.settings.get(node.test.id),bool):
            selected=node.body if self.settings[node.test.id] else node.orelse
            result=[]
            for child in selected:
                value=self.visit(child)
                if isinstance(value,list): result.extend(value)
                elif value is not None: result.append(value)
            return result
        return self.generic_visit(node)

    def visit_ClassDef(self,node):
        if node.name=="SpecialIndicatorsPage" and not self.settings["SHOW_SPECIAL"]: return None
        if node.name=="MarketEventsPage" and not self.settings["SHOW_EVENTS"]: return None
        if node.name=="MarketOverviewPage" and not self.settings["SHOW_DETAIL"]:
            node.body=[n for n in node.body if not isinstance(n,ast.FunctionDef) or n.name not in {"build_details","draw_details"}]
        if node.name=="MarketEventsPage" and not self.settings["SHOW_EVENT_DETAIL"]:
            node.body=[n for n in node.body if not isinstance(n,ast.FunctionDef) or n.name!="select_event"]
        return self.generic_visit(node)


def restrict_bundle(bundle,stage):
    settings=profile(stage);result=deepcopy(bundle)
    allowed={item[0] for item in settings["FREQUENCY_OPTIONS"]}
    result["views"]={k:v for k,v in result["views"].items() if v["frequency"] in allowed}
    for view in result["views"].values():
        if not settings["SHOW_DETAIL"]:
            view["term"]=[];view["book"]=None;view["book_valid_until"]=None
            view["book_reason"]="";view["frames"].pop("regression",None)
            view.pop("pair_research",None)
        if not settings["SHOW_SPECIAL"]:
            view["values"]={k:v for k,v in view["values"].items() if k in {"basis_bp","spread"}}
            view["reasons"]={k:v for k,v in view["reasons"].items() if k in view["values"]}
            view["analytics"]={k:v for k,v in view.get("analytics",{}).items() if k=="calendar_bp"}
            view["factors"]=[];view["relative_value"]=[]
        else:
            view["factors"]=[f for f in view["factors"] if all(i.get("frequency") in allowed or
                (settings["SHOW_DETAIL"] and i.get("frequency")=="实时观测") for i in f["spec"]["inputs"])]
        if not settings["SHOW_EVENTS"]: view["events"]=[]
        elif not settings["SHOW_EVENT_DETAIL"]:
            view["events"]=[{k:v for k,v in e.items() if k in {"event_time","product","type","title","value","unit","threshold","status","quality","reason"}}
                            for e in view["events"]]
    return result


def prune_imports(tree):
    used={n.id for n in ast.walk(tree) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load)}
    for node in tree.body:
        if isinstance(node,ast.ImportFrom) and node.module=="presentation":
            node.names=[a for a in node.names if (a.asname or a.name) in used]
    tree.body=[n for n in tree.body if not isinstance(n,ast.ImportFrom) or n.names]
    return tree

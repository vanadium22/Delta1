"""Developer calculation plus automatic publication for the shared viewer."""
from copy import deepcopy
import json
from pathlib import Path
import time

from .model import NativeModel
from .publication import DEFAULT_PUBLISH_ROOT, PRODUCTS, FREQUENCIES, make_bundle, write_publication, utc_now, decode_state
from .analytics import cross_product_metrics
from .pair_research import build_research


class DeveloperModel(NativeModel):
    edition = "developer"

    def __init__(self,local_root=None,publish_root=None):
        super().__init__(local_root)
        self.config.setdefault("publish_root",str(DEFAULT_PUBLISH_ROOT))
        if publish_root: self.config["publish_root"]=str(Path(publish_root).resolve())
        self._bundle = None
        self._bundle_key = None
        self._heartbeat = 0

    @property
    def publish_root(self):
        return Path(self.config["publish_root"])

    def _publication_key(self,request):
        return json.dumps([bool(request.get("demo")),self.source_signature(),self.config,self.formulas],sort_keys=True)

    def snapshot(self,request):
        if self.config.get("dashboard_mode") == "nonregression" and not request.get("demo"):
            return super().snapshot(request)
        observed_key = self._publication_key(request)
        state = super().snapshot(request)
        if request.get("as_of"): return state  # Private replay never replaces the shared latest view.
        try:
            if observed_key!=self._bundle_key or self._bundle is None:
                worker = NativeModel(self.local_root)
                worker.config = deepcopy(self.config)
                worker.formulas = deepcopy(self.formulas)
                states = []
                try:
                    for product in PRODUCTS:
                        for frequency in FREQUENCIES:
                            if (product,frequency)==(state["product"],state["frequency"]):
                                states.append(state)
                            else:
                                states.append(worker.snapshot({"product":product,"frequency":frequency,
                                    "demo":state["demo"],"as_of":state["as_of"],"save":False}))
                finally:
                    worker.close()
                for frequency in FREQUENCIES:
                    group={s["product"]:s for s in states if s["frequency"]==frequency}
                    pairs=cross_product_metrics(group)
                    research=build_research(group)
                    for item in group.values():
                        item["relative_value"]=pairs
                        item["pair_research"]=research
                bundle = make_bundle(states,demo=state["demo"])
                write_publication(self.publish_root,bundle)
                self._bundle = bundle
                self._bundle_key = observed_key
                self._heartbeat = time.monotonic()
            else:
                self._beat()
            state["publication_id"] = self._bundle["snapshot_id"]
            published=self._bundle["views"][state["product"]+":"+state["frequency"]]
            state["pair_research"]=deepcopy(published.get("pair_research",{}))
        except Exception as exc:
            state["publish_error"] = str(exc)
        return state

    def market_states(self,frequency,demo=False):
        if self._bundle and self._bundle["demo"]==bool(demo):
            return {product:decode_state(self._bundle["views"][product+":"+frequency]) for product in PRODUCTS}
        return {}

    def _beat(self):
        if self._bundle is not None and time.monotonic()-self._heartbeat>=10:
            self._bundle["heartbeat_at"] = utc_now()
            write_publication(self.publish_root,self._bundle)
            self._heartbeat = time.monotonic()

    def auto_snapshot(self,request):
        if self.config.get("dashboard_mode") == "nonregression": return self.snapshot(request)
        if self._publication_key(request)!=self._bundle_key:
            return self.snapshot(request)
        self._beat()
        return None

    def maintain_publication(self,request):
        # Called while the developer is replaying; the replay UI keeps its state.
        return self.auto_snapshot({**request,"as_of":None,"save":False})

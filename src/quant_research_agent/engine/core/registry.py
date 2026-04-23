from typing import Any, Dict, List, Optional, Type

from ..nodes.ai.research_chat import ResearchChatStep
from ..nodes.data.market_bars import MarketBarsStep
from ..nodes.factors.momentum import MomentumStep
from ..nodes.factors.rank import RankStep
from ..nodes.output.report import ReportStep
from ..nodes.triggers.manual import ManualTriggerStep


class RuntimeCatalog:
    def __init__(self) -> None:
        self._constructors: Dict[str, Type] = {}
        self._install_defaults()

    def create(self, kind: str) -> Any:
        constructor = self._constructors.get(kind)
        if constructor is None:
            raise ValueError("Unknown step kind: {0}".format(kind))
        return constructor()

    def register(self, kind: str, step_cls: Type) -> None:
        self._constructors[kind] = step_cls

    def supported_kinds(self) -> List[str]:
        return sorted(self._constructors.keys())

    def _install_defaults(self) -> None:
        self.register("trigger.manual", ManualTriggerStep)
        self.register("data.market_bars", MarketBarsStep)
        self.register("factor.momentum", MomentumStep)
        self.register("factor.rank", RankStep)
        self.register("research_chat", ResearchChatStep)
        self.register("output.report", ReportStep)


_catalog_singleton: Optional[RuntimeCatalog] = None


def get_registry() -> RuntimeCatalog:
    global _catalog_singleton
    if _catalog_singleton is None:
        _catalog_singleton = RuntimeCatalog()
    return _catalog_singleton


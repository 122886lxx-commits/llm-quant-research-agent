from typing import Any, Dict, List


def get_catalog() -> List[Dict[str, Any]]:
    return [descriptor.summary() for descriptor in _DESCRIPTORS]


def get_details(kind: str) -> Dict[str, Any]:
    descriptor = _by_kind().get(kind)
    if descriptor is None:
        return {"error": "Unknown kind: {0}".format(kind)}
    return descriptor.details()


class _StepDescriptor:
    def __init__(
        self,
        kind: str,
        purpose: str,
        required_fields: List[str],
        sample: Dict[str, Any],
        output_fields: List[str],
        notes: List[str],
    ) -> None:
        self.kind = kind
        self.purpose = purpose
        self.required_fields = required_fields
        self.sample = sample
        self.output_fields = output_fields
        self.notes = notes

    def summary(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "purpose": self.purpose,
            "required_fields": list(self.required_fields),
            "example_config": dict(self.sample),
            "output_fields": list(self.output_fields),
        }

    def details(self) -> Dict[str, Any]:
        payload = self.summary()
        payload["notes"] = list(self.notes)
        return payload


def _by_kind() -> Dict[str, _StepDescriptor]:
    return {descriptor.kind: descriptor for descriptor in _DESCRIPTORS}


_DESCRIPTORS = [
    _StepDescriptor(
        kind="trigger.manual",
        purpose="Seed the workflow with initial values.",
        required_fields=[],
        sample={"universe": ["AAPL", "MSFT", "NVDA"]},
        output_fields=["all input fields are returned as-is"],
        notes=[
            "Usually the first step in a plan.",
            "Its output can be referenced later with $step_id['field'].",
        ],
    ),
    _StepDescriptor(
        kind="data.market_bars",
        purpose="Fetch grouped daily bar series for one or more symbols.",
        required_fields=["symbols"],
        sample={"symbols": "$trigger['universe']", "lookback_days": 5},
        output_fields=["<symbol> -> [{date, close}, ...]"],
        notes=[
            "Use BaoStock-style symbols such as sh.600000 for live queries.",
            "Demo symbols AAPL, MSFT, and NVDA come from the fixture dataset.",
            "Return value is a grouped symbol -> bars mapping.",
        ],
    ),
    _StepDescriptor(
        kind="factor.momentum",
        purpose="Compute a momentum score map from grouped bars.",
        required_fields=["bars"],
        sample={"bars": "$bars", "window": 3},
        output_fields=["scores", "coverage", "window"],
        notes=[
            "The node expects grouped bars, not a single flat candle list.",
            "Downstream rank steps usually consume $momentum['scores'].",
        ],
    ),
    _StepDescriptor(
        kind="factor.rank",
        purpose="Order symbols using a score mapping.",
        required_fields=["values"],
        sample={"values": "$momentum['scores']", "descending": True},
        output_fields=["ordered", "top"],
        notes=[
            "descending=true means highest score first.",
            "The node returns ordered rows and a top-symbol list.",
        ],
    ),
    _StepDescriptor(
        kind="research_chat",
        purpose="Generate a natural-language explanation about upstream research outputs.",
        required_fields=["prompt"],
        sample={"prompt": "Explain this momentum ranking: $rank['ordered']"},
        output_fields=["content", "model", "finish_reason"],
        notes=[
            "Use runtime references such as $rank['ordered'] instead of static copied tool output.",
            "Prefer omitting config.model so the runtime can use RESEARCH_CHAT_MODEL.",
            "Do not hardcode legacy model names such as gpt-3.5-turbo.",
        ],
    ),
    _StepDescriptor(
        kind="output.report",
        purpose="Collect final text sections into a simple report payload.",
        required_fields=["sections"],
        sample={"sections": ["$chat['content']"]},
        output_fields=["sections"],
        notes=["Use this as an optional final wrapper around research outputs."],
    ),
]


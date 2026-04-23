import json
import re
from typing import Any, Dict, Iterable, Optional, Tuple

from ...permissions import PermissionPolicy


REFERENCE_PATTERN = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*(?:\[['\"][^'\"]+['\"]\]|\[\d+\])*")


class ExecutionContext:
    def __init__(self, pipeline_id: str, permission_policy: Optional[PermissionPolicy] = None):
        self.pipeline_id = pipeline_id
        self.step_outputs: Dict[str, Any] = {}
        self.permission_policy = permission_policy

    def set_output(self, step_id: str, output: Any) -> None:
        self.step_outputs[step_id] = output

    def get_output(self, step_id: str) -> Any:
        return self.step_outputs[step_id]

    def materialize_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self.materialize_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.materialize_value(item) for item in value]
        if isinstance(value, str):
            return self.materialize_text(value)
        return value

    def materialize_text(self, text: str) -> Any:
        if REFERENCE_PATTERN.fullmatch(text):
            return self.resolve_reference(text)

        def replace(match: re.Match[str]) -> str:
            resolved = self.resolve_reference(match.group(0))
            if isinstance(resolved, (dict, list)):
                return json.dumps(resolved, ensure_ascii=False)
            return str(resolved)

        return REFERENCE_PATTERN.sub(replace, text)

    def resolve_reference(self, ref: str) -> Any:
        root_name, access_path = self._split_reference(ref)
        value = self.get_output(root_name)
        for accessor in access_path:
            value = value[accessor]
        return value

    def _split_reference(self, ref: str) -> Tuple[str, Iterable[Any]]:
        if not isinstance(ref, str) or not ref.startswith("$"):
            raise ValueError("Invalid reference: {0}".format(ref))

        expression = ref[1:]
        root_match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)", expression)
        if root_match is None:
            raise ValueError("Invalid reference root: {0}".format(ref))

        root_name = root_match.group(1)
        remainder = expression[len(root_name):]
        return root_name, list(self._parse_accessors(remainder))

    def _parse_accessors(self, text: str) -> Iterable[Any]:
        token_pattern = re.compile(r"\[['\"]([^'\"]+)['\"]\]|\[(\d+)\]")
        for match in token_pattern.finditer(text):
            field_name = match.group(1)
            if field_name is not None:
                yield field_name
            else:
                yield int(match.group(2))

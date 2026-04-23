from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from ..engine.core.builder import PipelineBuilder
from .catalog import get_catalog as catalog_list
from .catalog import get_details as catalog_details

ToolHandler = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]

_SUPPORTED_KINDS = [
    "trigger.manual",
    "data.market_bars",
    "factor.momentum",
    "factor.rank",
    "research_chat",
    "output.report",
]

_active_builder: Optional[PipelineBuilder] = None


def bind_builder(builder: PipelineBuilder) -> None:
    global _active_builder
    _active_builder = builder


def get_tool_specs() -> List[Dict[str, Any]]:
    object_schema = {
        "type": "object",
        "description": "Step config. Use literal values or runtime references like $step_id['field'].",
    }
    return [
        _function_spec(
            name="add_step",
            description=(
                "Create a draft workflow step. Inspect step details first when the config shape is unclear."
            ),
            properties={
                "kind": {"type": "string", "enum": list(_SUPPORTED_KINDS)},
                "step_id": {"type": "string"},
                "config": object_schema,
            },
            required=["kind", "config"],
        ),
        _function_spec(
            name="update_step",
            description="Modify a draft step config and immediately re-evaluate it.",
            properties={"step_id": {"type": "string"}, "config": object_schema},
            required=["step_id", "config"],
        ),
        _function_spec(
            name="connect_steps",
            description="Declare that one step should run before another step.",
            properties={"source_id": {"type": "string"}, "target_id": {"type": "string"}},
            required=["source_id", "target_id"],
        ),
        _function_spec("get_catalog", "Inspect available step kinds at a high level.", {}, []),
        _function_spec(
            "get_details",
            "Inspect one step kind in detail, including example config, output fields, and notes.",
            {"kind": {"type": "string", "enum": list(_SUPPORTED_KINDS)}},
            ["kind"],
        ),
        _function_spec("get_pipeline", "Export the current draft plan when it is coherent enough to run.", {}, []),
    ]


async def execute_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if _active_builder is None:
        return {"success": False, "error": "Builder not bound", "stage": "tooling"}

    handlers = _tool_handlers(_active_builder)
    if name not in handlers:
        return {"success": False, "error": "Unknown tool: {0}".format(name), "stage": "tooling"}

    try:
        return await handlers[name](arguments)
    except Exception as exc:
        return {"success": False, "error": str(exc), "stage": "tooling"}


def _function_spec(name: str, description: str, properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


def _tool_handlers(builder: PipelineBuilder) -> Dict[str, ToolHandler]:
    return {
        "add_step": lambda payload: _add_step(builder, payload),
        "update_step": lambda payload: _update_step(builder, payload),
        "connect_steps": lambda payload: _connect_steps(builder, payload),
        "get_catalog": lambda payload: _get_catalog(payload),
        "get_details": lambda payload: _get_details(payload),
        "get_pipeline": lambda payload: _get_pipeline(builder, payload),
    }


async def _add_step(builder: PipelineBuilder, payload: Dict[str, Any]) -> Dict[str, Any]:
    kind = payload["kind"]
    if kind not in _SUPPORTED_KINDS:
        return {"success": False, "action": "add_step", "stage": "tooling", "error": "Unsupported kind: {0}".format(kind)}

    created_id = builder.add_step(kind=kind, config=payload.get("config", {}), step_id=payload.get("step_id"))
    result = await _run_step(builder, created_id)
    result["action"] = "add_step"
    return result


async def _update_step(builder: PipelineBuilder, payload: Dict[str, Any]) -> Dict[str, Any]:
    step_id = payload["step_id"]
    if step_id not in set(builder.snapshot_step_ids()):
        return {"success": False, "action": "update_step", "stage": "tooling", "error": "Unknown step id: {0}".format(step_id)}

    builder.update_step(step_id, payload.get("config", {}))
    result = await _run_step(builder, step_id)
    result["action"] = "update_step"
    return result


async def _connect_steps(builder: PipelineBuilder, payload: Dict[str, Any]) -> Dict[str, Any]:
    known_ids = set(builder.snapshot_step_ids())
    if payload["source_id"] not in known_ids:
        return {"success": False, "action": "connect_steps", "stage": "tooling", "error": "Unknown source step id: {0}".format(payload["source_id"])}
    if payload["target_id"] not in known_ids:
        return {"success": False, "action": "connect_steps", "stage": "tooling", "error": "Unknown target step id: {0}".format(payload["target_id"])}

    builder.connect_steps(payload["source_id"], payload["target_id"])
    return {"success": True, "action": "connect_steps", "source_id": payload["source_id"], "target_id": payload["target_id"]}


async def _get_catalog(_: Dict[str, Any]) -> Dict[str, Any]:
    return {"success": True, "action": "get_catalog", "catalog": catalog_list()}


async def _get_details(payload: Dict[str, Any]) -> Dict[str, Any]:
    details = catalog_details(payload["kind"])
    if "error" in details:
        return {"success": False, "action": "get_details", "error": details["error"]}
    return {"success": True, "action": "get_details", "details": details}


async def _get_pipeline(builder: PipelineBuilder, _: Dict[str, Any]) -> Dict[str, Any]:
    pipeline = builder.get_pipeline()
    validation_error = _pipeline_validation_error(pipeline)
    if validation_error is not None:
        return {"success": False, "action": "get_pipeline", "error": validation_error, "pipeline": pipeline}
    return {"success": True, "action": "get_pipeline", "pipeline": pipeline}


async def _run_step(builder: PipelineBuilder, step_id: str) -> Dict[str, Any]:
    step_snapshot = builder.get_step_snapshot(step_id)
    try:
        output = await builder.execute_step(step_id)
    except Exception as exc:
        return {
            "success": False,
            "step_id": step_id,
            "kind": step_snapshot["kind"],
            "attempted_config": step_snapshot.get("config", {}),
            "error": str(exc),
            "stage": "execution",
        }
    return {"success": True, "step_id": step_id, "kind": step_snapshot["kind"], "output": output, "stage": "execution"}


def _pipeline_validation_error(pipeline: Dict[str, Any]) -> Optional[str]:
    steps = pipeline.get("steps", [])
    if not steps:
        return "Pipeline is empty"

    step_ids = [step.get("id") for step in steps]
    if any(not step_id for step_id in step_ids):
        return "Pipeline contains a step with a missing id"
    if len(step_ids) != len(set(step_ids)):
        return "Pipeline contains duplicate step ids"

    known_ids = set(step_ids)
    relationship_count = 0
    inbound_ids: Set[str] = set()
    for step in steps:
        for target_id in step.get("next", []):
            if target_id not in known_ids:
                return "Unknown target '{0}' referenced by '{1}'".format(target_id, step["id"])
            relationship_count += 1
            inbound_ids.add(target_id)
        reference_roots = _extract_reference_roots(step.get("config", {})) & known_ids
        relationship_count += len(reference_roots)
        if reference_roots:
            inbound_ids.add(step["id"])

    if len(steps) > 1 and relationship_count == 0:
        return "Pipeline has multiple steps but no connections or references"
    disconnected_ids = [step_id for step_id in step_ids[1:] if step_id not in inbound_ids]
    if disconnected_ids:
        return "Pipeline has disconnected non-initial steps: {0}".format(", ".join(disconnected_ids))
    return None


def _extract_reference_roots(value: Any) -> Set[str]:
    refs: Set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            refs |= _extract_reference_roots(item)
        return refs
    if isinstance(value, list):
        for item in value:
            refs |= _extract_reference_roots(item)
        return refs
    if isinstance(value, str):
        for token in value.split("$")[1:]:
            refs.add(token.split("[")[0].split()[0].strip(".,:;)"))
    return refs


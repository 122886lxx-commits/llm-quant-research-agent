import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from .agent.react_loop import ReactLoopAgent
from .agent.tracing import (
    build_agent_trace,
    build_plan_trace,
    create_run_dir,
    format_trace_summary,
    load_trace,
    replay_trace,
    write_trace,
)
from .agent.artifacts import write_run_artifacts
from .agent.workflow import AgentWorkflowRunner
from .engine.core.engine import PipelineEngine
from .evaluation import EvaluationRunner
from .permissions import PermissionPolicy


def main() -> None:
    parser = argparse.ArgumentParser(description="Run or plan quant research workflows.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Execute a YAML pipeline.")
    run_parser.add_argument("pipeline", type=Path)
    run_parser.add_argument("--allow", default="read", help="Comma-separated permissions, e.g. read,network.")
    run_parser.add_argument("--output-dir", type=Path)
    run_parser.add_argument("--save-pipeline", action=argparse.BooleanOptionalAction, default=True)
    run_parser.add_argument("--save-report", action=argparse.BooleanOptionalAction, default=True)

    plan_parser = subparsers.add_parser("plan", help="Ask the LLM planner to draft a pipeline.")
    plan_parser.add_argument("prompt")
    plan_parser.add_argument("--execute", action="store_true", help="Execute the generated pipeline.")
    plan_parser.add_argument("--allow", default="read", help="Comma-separated permissions, e.g. read,network,write_artifact.")
    plan_parser.add_argument("--output-dir", type=Path)
    plan_parser.add_argument("--save-pipeline", action=argparse.BooleanOptionalAction, default=True)
    plan_parser.add_argument("--save-report", action=argparse.BooleanOptionalAction, default=True)

    agent_parser = subparsers.add_parser("agent", help="Plan, run, verify, and repair a research pipeline.")
    agent_parser.add_argument("prompt")
    agent_parser.add_argument("--max-repairs", type=int, default=1)
    agent_parser.add_argument("--allow", default="read", help="Comma-separated permissions, e.g. read,network,write_artifact.")
    agent_parser.add_argument("--output-dir", type=Path)
    agent_parser.add_argument("--save-pipeline", action=argparse.BooleanOptionalAction, default=True)
    agent_parser.add_argument("--save-report", action=argparse.BooleanOptionalAction, default=True)

    trace_parser = subparsers.add_parser("trace", help="Summarize a saved agent trace.")
    trace_parser.add_argument("trace_json", type=Path)

    replay_parser = subparsers.add_parser("replay", help="Replay the pipeline stored in a trace file.")
    replay_parser.add_argument("trace_json", type=Path)
    replay_parser.add_argument("--allow", default="read", help="Comma-separated permissions, e.g. read,network.")

    eval_parser = subparsers.add_parser("eval", help="Run deterministic evaluation tasks.")
    eval_parser.add_argument("tasks", type=Path)
    eval_parser.add_argument("--output", type=Path, default=Path("evals/results/latest.json"))
    eval_parser.add_argument("--allow", default="read", help="Comma-separated permissions, e.g. read,write_artifact.")

    args = parser.parse_args()
    asyncio.run(_dispatch(args))


async def _dispatch(args: Any) -> None:
    if args.command == "run":
        policy = _permission_policy(args)
        result = await PipelineEngine(permission_policy=policy).run_pipeline(args.pipeline)
        if args.output_dir:
            artifact_paths = write_run_artifacts(
                prompt="Run pipeline file: {0}".format(args.pipeline),
                pipeline=_read_pipeline_dict(args.pipeline),
                execution_result=result,
                output_dir=args.output_dir,
                permission_policy=policy,
                save_pipeline=args.save_pipeline,
                save_report=args.save_report,
            )
            print("Artifacts: {0}".format(json.dumps(artifact_paths, ensure_ascii=False)))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if args.command == "plan":
        policy = _permission_policy(args)
        try:
            planning_result = await ReactLoopAgent(permission_policy=policy).run(args.prompt)
        except Exception as exc:
            if args.execute:
                trace = build_plan_trace(
                    args.prompt,
                    {},
                    None,
                    "failed_planning",
                    [{"stage": "plan", "message": str(exc)}],
                    permission_decisions=policy.to_trace(),
                )
                print("Trace: {0}".format(write_trace(trace, permission_policy=policy)))
            raise
        pipeline = planning_result["pipeline"]
        print("Generated Pipeline:")
        print(json.dumps(pipeline, indent=2, ensure_ascii=False))
        if args.execute:
            run_result = None
            final_status = "success"
            errors = []
            try:
                run_result = await PipelineEngine(permission_policy=policy).run_pipeline(pipeline)
            except Exception as exc:
                final_status = "failed_execution"
                errors.append({"stage": "run", "message": str(exc)})
                raise
            finally:
                output_dir = args.output_dir or create_run_dir()
                artifact_paths = {}
                if run_result is not None:
                    artifact_paths = write_run_artifacts(
                        prompt=args.prompt,
                        pipeline=pipeline,
                        execution_result=run_result,
                        output_dir=output_dir,
                        permission_policy=policy,
                        save_pipeline=args.save_pipeline,
                        save_report=args.save_report,
                    )
                trace = build_plan_trace(
                    args.prompt,
                    planning_result,
                    run_result,
                    final_status,
                    errors,
                    permission_decisions=policy.to_trace(),
                )
                trace_path = write_trace(trace, run_dir=output_dir, permission_policy=policy)
                print("Trace: {0}".format(trace_path))
                if artifact_paths:
                    print("Artifacts: {0}".format(json.dumps(artifact_paths, ensure_ascii=False)))
            print("Execution Result:")
            print(json.dumps(run_result, indent=2, ensure_ascii=False))
        return

    if args.command == "agent":
        policy = _permission_policy(args)
        state = await AgentWorkflowRunner(permission_policy=policy).run(args.prompt, max_repairs=args.max_repairs)
        output_dir = args.output_dir or create_run_dir()
        artifact_paths = write_run_artifacts(
            prompt=args.prompt,
            pipeline=state.current_pipeline or {},
            execution_result=state.execution_result,
            output_dir=output_dir,
            permission_policy=policy,
            save_pipeline=args.save_pipeline,
            save_report=args.save_report,
        )
        trace_path = write_trace(build_agent_trace(state), run_dir=output_dir, permission_policy=policy)
        print("Agent Stages:")
        for item in state.stage_history:
            print("  {0}: {1}".format(item["stage"], item["status"]))
        print("Final Status: {0}".format(state.status))
        print("Trace: {0}".format(trace_path))
        print("Artifacts: {0}".format(json.dumps(artifact_paths, ensure_ascii=False)))
        print("Agent Run:")
        print(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
        return

    if args.command == "trace":
        print(format_trace_summary(load_trace(args.trace_json)))
        return

    if args.command == "replay":
        policy = _permission_policy(args)
        result = await replay_trace(args.trace_json, engine=PipelineEngine(permission_policy=policy))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if args.command == "eval":
        policy = _permission_policy(args)
        summary = await EvaluationRunner(permission_policy=policy).run_path(args.tasks, output=args.output)
        compact_summary = {key: value for key, value in summary.items() if key != "tasks"}
        print(json.dumps(compact_summary, indent=2, ensure_ascii=False))
        print("Evaluation results: {0}".format(args.output))
        print("Evaluation markdown: {0}".format(args.output.with_suffix(".md")))
        return

    raise ValueError("Unsupported command: {0}".format(args.command))


def _permission_policy(args: Any) -> PermissionPolicy:
    return PermissionPolicy.from_csv(getattr(args, "allow", "read"), interactive=sys.stdin.isatty())


def _read_pipeline_dict(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return payload.get("pipeline", payload)

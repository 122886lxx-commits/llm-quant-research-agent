import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from .agent.react_loop import ReactLoopAgent
from .agent.tracing import (
    build_agent_trace,
    build_plan_trace,
    format_trace_summary,
    load_trace,
    replay_trace,
    write_trace,
)
from .agent.workflow import AgentWorkflowRunner
from .engine.core.engine import PipelineEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Run or plan quant research workflows.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Execute a YAML pipeline.")
    run_parser.add_argument("pipeline", type=Path)

    plan_parser = subparsers.add_parser("plan", help="Ask the LLM planner to draft a pipeline.")
    plan_parser.add_argument("prompt")
    plan_parser.add_argument("--execute", action="store_true", help="Execute the generated pipeline.")

    agent_parser = subparsers.add_parser("agent", help="Plan, run, verify, and repair a research pipeline.")
    agent_parser.add_argument("prompt")
    agent_parser.add_argument("--max-repairs", type=int, default=1)

    trace_parser = subparsers.add_parser("trace", help="Summarize a saved agent trace.")
    trace_parser.add_argument("trace_json", type=Path)

    replay_parser = subparsers.add_parser("replay", help="Replay the pipeline stored in a trace file.")
    replay_parser.add_argument("trace_json", type=Path)

    args = parser.parse_args()
    asyncio.run(_dispatch(args))


async def _dispatch(args: Any) -> None:
    if args.command == "run":
        result = await PipelineEngine().run_pipeline(args.pipeline)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if args.command == "plan":
        try:
            planning_result = await ReactLoopAgent().run(args.prompt)
        except Exception as exc:
            if args.execute:
                trace = build_plan_trace(
                    args.prompt,
                    {},
                    None,
                    "failed_planning",
                    [{"stage": "plan", "message": str(exc)}],
                )
                print("Trace: {0}".format(write_trace(trace)))
            raise
        pipeline = planning_result["pipeline"]
        print("Generated Pipeline:")
        print(json.dumps(pipeline, indent=2, ensure_ascii=False))
        if args.execute:
            run_result = None
            final_status = "success"
            errors = []
            try:
                run_result = await PipelineEngine().run_pipeline(pipeline)
            except Exception as exc:
                final_status = "failed_execution"
                errors.append({"stage": "run", "message": str(exc)})
                raise
            finally:
                trace = build_plan_trace(args.prompt, planning_result, run_result, final_status, errors)
                trace_path = write_trace(trace)
                print("Trace: {0}".format(trace_path))
            print("Execution Result:")
            print(json.dumps(run_result, indent=2, ensure_ascii=False))
        return

    if args.command == "agent":
        state = await AgentWorkflowRunner().run(args.prompt, max_repairs=args.max_repairs)
        trace_path = write_trace(build_agent_trace(state))
        print("Agent Stages:")
        for item in state.stage_history:
            print("  {0}: {1}".format(item["stage"], item["status"]))
        print("Final Status: {0}".format(state.status))
        print("Trace: {0}".format(trace_path))
        print("Agent Run:")
        print(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
        return

    if args.command == "trace":
        print(format_trace_summary(load_trace(args.trace_json)))
        return

    if args.command == "replay":
        result = await replay_trace(args.trace_json)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    raise ValueError("Unsupported command: {0}".format(args.command))

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from .agent.react_loop import ReactLoopAgent
from .engine.core.engine import PipelineEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Run or plan quant research workflows.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Execute a YAML pipeline.")
    run_parser.add_argument("pipeline", type=Path)

    plan_parser = subparsers.add_parser("plan", help="Ask the LLM planner to draft a pipeline.")
    plan_parser.add_argument("prompt")
    plan_parser.add_argument("--execute", action="store_true", help="Execute the generated pipeline.")

    args = parser.parse_args()
    asyncio.run(_dispatch(args))


async def _dispatch(args: Any) -> None:
    if args.command == "run":
        result = await PipelineEngine().run_pipeline(args.pipeline)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if args.command == "plan":
        planning_result = await ReactLoopAgent().run(args.prompt)
        pipeline = planning_result["pipeline"]
        print("Generated Pipeline:")
        print(json.dumps(pipeline, indent=2, ensure_ascii=False))
        if args.execute:
            run_result = await PipelineEngine().run_pipeline(pipeline)
            print("Execution Result:")
            print(json.dumps(run_result, indent=2, ensure_ascii=False))
        return

    raise ValueError("Unsupported command: {0}".format(args.command))


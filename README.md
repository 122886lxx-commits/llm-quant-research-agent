# LLM Quant Research Agent

A Python workflow engine where an LLM planner builds executable quant research pipelines through generic tools.

The project demonstrates three ideas:

- a small YAML runtime for step-based research workflows
- a handwritten ReAct-style planner loop that edits a pipeline with generic tools
- real integrations for market bars and OpenAI-compatible chat-completions APIs

## Example Workflow

```text
trigger.manual -> data.market_bars -> factor.momentum -> factor.rank -> research_chat
```

The runtime resolves references such as `$rank['ordered']`, including references embedded inside prompt strings.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Run deterministic local tests:

```bash
python -m unittest discover -s tests
```

Run a deterministic YAML example without an LLM key:

```bash
python -m quant_research_agent run examples/momentum_report_pipeline.yaml
```

Run the LLM-backed YAML example:

```bash
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
export RESEARCH_CHAT_MODEL=qwen-plus
python -m quant_research_agent run examples/momentum_pipeline.yaml
```

Generate a pipeline with the LLM planner and execute it:

```bash
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
export REACT_MODEL=qwen-plus
export RESEARCH_CHAT_MODEL=qwen-plus
python -m quant_research_agent plan "Use market bars to compute momentum, rank the symbols, and explain the result." --execute
```

## Market Data Behavior

- Exchange-prefixed symbols such as `sh.600000` or `sz.000001` are fetched through BaoStock.
- Demo symbols `AAPL`, `MSFT`, and `NVDA` are served from `datasets/daily_bars.json` for deterministic local runs.

## Architecture

- `quant_research_agent.engine`: YAML parser, dependency scheduler, execution context, registry, runtime nodes
- `quant_research_agent.agent`: catalog metadata, generic planner tools, handwritten ReAct loop
- `examples`: executable pipeline specs
- `tests`: regression tests for runtime execution, reference interpolation, tool validation, and model fallback

## Why This Project Matters

This is intentionally not a trading bot. It is a research workflow prototype: the LLM plans a reproducible pipeline, the runtime executes that pipeline deterministically, and the final explanation is generated from actual upstream outputs.

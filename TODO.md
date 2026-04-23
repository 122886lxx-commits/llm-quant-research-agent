# Agent Development Roadmap

Goal: evolve this repository from a workflow demo into a deeper Agent engineering project that demonstrates planning, execution, verification, repair, tracing, evaluation, permissions, and artifact generation.

## P0: Plan-Run-Verify-Repair Loop

Why it matters:

- Shows the agent is not just a single prompt or one-shot tool caller.
- Demonstrates explicit control flow, state transitions, failure recovery, and completion criteria.

Tasks:

- [x] Add an `AgentRunState` model that tracks prompt, current pipeline, execution result, errors, repair attempts, and final status.
- [x] Split current planner behavior into stages: `plan`, `run`, `verify`, `repair`, `finalize`.
- [x] Add a verifier that checks pipeline shape, required outputs, non-empty factor scores, and final report quality.
- [x] Add a repair loop that feeds verifier/runtime errors back into the planner with targeted instructions.
- [x] Add max repair attempts and explicit terminal statuses: `success`, `failed_planning`, `failed_execution`, `failed_verification`, `max_repairs_exceeded`.

Acceptance:

- [x] A deliberately broken pipeline can be repaired automatically at least once.
- [x] CLI command prints each stage and final status.
- [x] Tests cover success, execution failure, verification failure, and max-repair behavior.

Demo command target:

```bash
python -m quant_research_agent agent "Rank AAPL, MSFT, NVDA by 3-day momentum and explain the result"
```

## P0: Agent Trace and Replay

Why it matters:

- Strong agent projects are inspectable, not opaque.
- Trace logs help show tool-call reasoning, debugging, and regression analysis.

Tasks:

- [x] Add a `runs/` output directory ignored by git.
- [x] Persist `trace.json` for every agent run.
- [x] Include prompt, model, messages, tool calls, tool results, generated pipeline, execution outputs, verifier results, repairs, timestamps, and final status.
- [x] Add `quant-agent trace <trace.json>` to summarize a run.
- [x] Add `quant-agent replay <trace.json>` to re-run the saved pipeline without asking the LLM again.

Acceptance:

- [x] Every `plan --execute` or `agent` run produces a trace file.
- [x] A trace can be replayed deterministically with fixture data.
- [x] Trace files contain no API keys or secrets.

Demo command target:

```bash
python -m quant_research_agent trace runs/latest/trace.json
python -m quant_research_agent replay runs/latest/trace.json
```

## P1: Evaluation Suite

Why it matters:

- Evaluations separate serious agent engineering from demos.
- Lets the project claim measurable planning/execution/repair quality.

Tasks:

- [x] Create `evals/tasks/*.yaml` with natural-language prompts and expected pipeline/output assertions.
- [x] Support evaluation dimensions: planning validity, execution success, output assertions, repair success, and tool-call count.
- [x] Add an eval runner: `python -m quant_research_agent eval evals/tasks`.
- [x] Produce `evals/results/latest.json` and a markdown summary table.
- [ ] Add baseline tasks for momentum ranking, volatility ranking, report generation, bad reference repair, missing step repair, and static prompt rejection.

Acceptance:

- [x] At least 20 eval tasks exist.
- [x] Eval summary reports planning success rate, execution success rate, verification success rate, and repair success rate.
- [x] CI can run deterministic evals without an LLM by replaying fixed pipelines.

Demo command target:

```bash
python -m quant_research_agent eval evals/tasks --output evals/results/latest.json
```

## P1: Self-Repair Scenarios

Why it matters:

- Repair is one of the strongest signals for real Agent engineering depth.
- Demonstrates that errors are not just surfaced, but actionable.

Tasks:

- [x] Add synthetic failure cases: missing reference, wrong field name, disconnected step, empty scores, unsupported symbol, missing API key, model not found.
- [x] Classify errors into `planning_error`, `config_error`, `data_error`, `provider_error`, and `verification_error`.
- [x] Add repair prompts specialized by error class.
- [x] Track repair diffs between pipeline versions.
- [x] Add tests for at least three repair classes.

Acceptance:

- [x] Agent can repair a missing dependency edge.
- [x] Agent can repair an unresolved reference.
- [x] Agent can recover from a provider model mismatch by using configured defaults.

Demo command target:

```bash
python -m quant_research_agent repair examples/broken_missing_reference.yaml
```

## P1: Permissioned Tools and Safety Boundaries

Why it matters:

- Real agents need permission boundaries, especially when tools can read, write, call networks, or mutate state.
- Shows production awareness beyond prompt engineering.

Tasks:

- [x] Add a tool permission model: `read`, `network`, `write_artifact`, `destructive`.
- [x] Require explicit approval for `network` and `write_artifact` in interactive mode.
- [x] Add a non-interactive policy flag: `--allow read,network`.
- [x] Prevent destructive actions by default.
- [x] Log all permission decisions into trace files.
- [x] Add secret redaction for env vars and trace payloads.

Acceptance:

- [x] Running a live BaoStock query requires `network` permission.
- [x] Writing artifacts requires `write_artifact` permission.
- [x] Tests prove secrets are redacted from traces.

Demo command target:

```bash
python -m quant_research_agent agent "Use live BaoStock data for sh.600000" --allow read,network,write_artifact
```

## P1: Artifact Generation

Why it matters:

- Agents should produce reusable outputs, not just chat text.
- Artifacts make the project feel like an engineering tool.

Tasks:

- [x] Add output directories per run: `runs/<timestamp>/`.
- [x] Save `generated_pipeline.yaml`, `run_result.json`, `research_report.md`, and `trace.json`.
- [x] Add markdown report rendering from rank/momentum/chat outputs.
- [x] Add CLI options: `--output-dir`, `--save-pipeline`, `--save-report`.
- [x] Add a deterministic report example that does not require LLM credentials.

Acceptance:

- [x] A run produces all expected artifacts.
- [x] Report includes prompt, pipeline summary, ranked table, and final explanation.
- [x] Saved pipeline can be re-run with `quant-agent run`.

Demo command target:

```bash
python -m quant_research_agent agent "Rank AAPL, MSFT, NVDA by momentum" --output-dir runs/demo
```

## P2: More Quant Research Nodes

Why it matters:

- Expands the project from a single demo into a richer research workflow engine.

Tasks:

- [ ] Add `factor.volatility`.
- [ ] Add `factor.rsi`.
- [ ] Add `factor.moving_average_cross`.
- [ ] Add `factor.mean_reversion`.
- [ ] Add `risk.volatility_filter`.
- [ ] Add `portfolio.equal_weight`.
- [ ] Add `portfolio.score_weight`.
- [ ] Update catalog metadata and examples for each node.

Acceptance:

- [ ] Each node has unit tests.
- [ ] At least three multi-factor pipeline examples exist.
- [ ] Agent can discover and compose the new nodes through generic tools.

## P2: Provider and Data Configuration

Why it matters:

- Makes the project easier to run across DashScope, OpenAI, and other OpenAI-compatible providers.

Tasks:

- [ ] Add `config.yaml` support for model provider, base URL, model names, market data mode, cache settings, and artifact paths.
- [ ] Add provider profiles: `dashscope`, `openai`, `local`.
- [ ] Add market data cache under `.cache/market_bars/`.
- [ ] Add `--config config.yaml` CLI option.
- [ ] Add `.env.example` variants for DashScope and OpenAI.

Acceptance:

- [ ] Same CLI command works with provider config instead of raw env vars.
- [ ] Market data cache avoids repeated live calls for the same date window.
- [ ] Tests cover config loading and cache hit/miss behavior.

## P2: Visual Demo Surface

Why it matters:

- Helps non-coding interviewers quickly understand the system.
- Useful for README screenshots and project demos.

Tasks:

- [ ] Add a Streamlit app or small FastAPI backend.
- [ ] Show prompt input, generated pipeline, execution trace, ranked output, and report.
- [ ] Add screenshots/GIF to README.
- [ ] Keep the CLI as the primary implementation path.

Acceptance:

- [ ] Demo can run locally in under one minute with fixture data.
- [ ] README includes a screenshot of the agent trace and output report.

## Resume Positioning Checklist

- [ ] README explains the difference between workflow runtime, planner, executor, verifier, and artifacts.
- [ ] README includes a trace screenshot or sample trace JSON.
- [ ] README includes an eval table with success metrics.
- [ ] GitHub Actions badge is green.
- [ ] The project has at least one demo command that works without API keys.
- [ ] The project has at least one demo command that uses an OpenAI-compatible provider such as DashScope/Qwen.

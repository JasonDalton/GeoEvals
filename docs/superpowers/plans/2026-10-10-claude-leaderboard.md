# Claude Leaderboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run `gis_correctness` and `human_context_access` against Claude Opus 5.5, Sonnet 5.5
and Haiku 5.5 through the local Claude Code CLI on a subscription, in a direct track and a
sandboxed-Python track, and publish a generated results table in `README.md`.

**Architecture:** A standard-library module runs `claude -p` with isolation flags and parses
its stream-json output. Two adapter classes (direct, python) build prompts from the case and
the benchmark spec and call it; the python track adds a stdio MCP server whose one tool runs
code in a per-case Docker container with no network. A leaderboard module turns committed run
results into a Markdown table between markers in the README.

**Tech Stack:** Python 3.11+, uv, pydantic, GeoPandas (Parquet to GeoJSON), Docker, Claude
Code 2.1.296 CLI, pytest, ruff, pyright.

**Spec:** `docs/superpowers/specs/2026-10-09-claude-leaderboard-design.md`

## Global Constraints

- Model IDs: `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`. Adapter names
  `claude_direct_<slug>` and `claude_python_<slug>`, slugs `opus_5_5`, `sonnet_5_5`,
  `haiku_5_5`.
- No API key: `ANTHROPIC_API_KEY` (and `ANTHROPIC_AUTH_TOKEN`) are removed from the CLI's
  environment; `apiKeySource` in the init event must be `none`.
- CLI flags: `--restricted --tools "" --strict-mcp-config --disable-slash-commands
  --no-session-persistence --permission-prompts none --effort high --output-format
  stream-json --verbose`, plus `--model`, `--system-prompt`, `--json-schema`,
  `--max-budget-usd`, and on the python track `--mcp-config` and `--allowedTools`. The user
  message goes on stdin. The CLI runs in a new empty temporary directory.
- No new runtime dependency; the core install is unchanged. No change to the run result schema.
- Never send `expected`, `strata`, `tolerances`, `metric_params` or `case_id` to the model.
- Sandbox: `--network none`, read-only root, `tmpfs` `/tmp`, caps dropped, non-root user,
  only `fixtures/` mounted read-only at `/bench/fixtures`, 60 s and 20 KB per `run_python` call,
  20 calls per case.
- Tokens: input = input + cache creation + cache read; output = output tokens; summed over
  `modelUsage`.
- No test calls a model. Docker tests carry the `docker` marker, excluded by default.
- American spelling; ruff line length 100; pyright standard mode.
- Commits carry no attribution trailer.

## Review Focus

1. **Large inputs:** a human-context case inlines about 125 KB of GeoJSON. Expected: it goes on
   stdin, not argv. Test: `test_user_message_goes_on_stdin_not_argv`.
2. **Worker killed on runner timeout:** the CLI and the container must not outlive the case.
   Expected: the adapter's own `case_timeout_s` fires first, kills the process group and
   removes the container. Tests: `test_timeout_kills_the_process_group` and
   `test_python_adapter_removes_the_container_on_error`.
3. **CLI missing or Docker not running:** expected a clear setup error, not a run of
   `adapter_error`s. Tests: `test_setup_fails_when_the_cli_is_missing` and
   `test_python_setup_fails_without_docker`.
4. **Usage limit in the middle of a run:** expected that this case and every later case are
   skipped and the leaderboard rejects the run. Tests: `test_usage_limit_skips_later_cases`
   and `test_build_rejects_runs_with_skipped_cases`.
5. **The model writes outside the sandbox or reads answers:** expected that the mount holds
   only fixtures, read-only, with no network. Test: `test_sandbox_isolation` (docker marker).

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/geoevals/leaderboard/__init__.py` | Package docstring only |
| `src/geoevals/leaderboard/claude_cli.py` | Build the CLI command, run it, parse stream-json, map errors |
| `src/geoevals/leaderboard/prompting.py` | Prompt templates, spec reading, schema cleanup, file inlining, user messages |
| `src/geoevals/adapters/prompts/direct_v1.md`, `python_v1.md` | Versioned system prompts |
| `src/geoevals/adapters/claude.py` | `ClaudeDirectAdapter`, `ClaudePythonAdapter`, config, trajectory building |
| `src/geoevals/leaderboard/sandbox.py` | Docker image build and per-case container operations |
| `src/geoevals/leaderboard/sandbox.Dockerfile` | Sandbox image |
| `src/geoevals/leaderboard/sandbox_mcp.py` | Stdio MCP server with `run_python` |
| `src/geoevals/leaderboard/table.py` | Load results, check acceptance and comparability, render, update README, add a run |
| `src/geoevals/cli.py` | `geoevals leaderboard add` and `geoevals leaderboard build` |
| `leaderboard/configs/{direct,python,pilot-direct,pilot-python}.yaml` | Run configs |
| `leaderboard/README.md` | How to run and add results |
| `tests/fake_claude.py` | Fake CLI that replays a scenario file |
| `tests/test_claude_cli.py`, `test_claude_adapters.py`, `test_sandbox.py`, `test_leaderboard.py` | Tests |

---

### Task 1: Claude CLI runner

**Files:**
- Create: `src/geoevals/leaderboard/__init__.py`, `src/geoevals/leaderboard/claude_cli.py`,
  `tests/fake_claude.py`
- Test: `tests/test_claude_cli.py`

**Interfaces:**
- Produces:
  - `CliCall(model: str, system_prompt: str, user_message: str, json_schema: dict, effort: str = "high", max_budget_usd: float = 5.0, timeout_s: float = 840.0, mcp_config: dict | None = None, allowed_tools: tuple[str, ...] = (), command: tuple[str, ...] = ("claude",))`
  - `CliResult(structured_output: dict | None, input_tokens: int, output_tokens: int, models: tuple[str, ...], num_turns: int, claude_code_version: str | None, events: list[dict])`
  - `build_command(call: CliCall, mcp_config_path: Path | None) -> list[str]`
  - `parse_events(stdout: str) -> list[dict]`
  - `check_result(events: list[dict], model: str) -> CliResult` (raises the errors below)
  - `run_cli(call: CliCall) -> CliResult`
  - `claude_code_version(command: Sequence[str] = ("claude",)) -> str` (`"unknown"` when the CLI is missing)
  - Errors (all subclasses of `ClaudeCliError(RuntimeError)`): `ClaudeTimeout`,
    `ClaudeRunError`, `ClaudeRefusal`, `ClaudeNoAnswer`, `ClaudeUnexpectedModel`,
    `ClaudeAuthError`, `ClaudeUsageLimit`

`tests/fake_claude.py` reads the JSON file named by the environment variable
`FAKE_CLAUDE_SCENARIO`: `{"events": [...], "exit_code": 0, "sleep_s": 0, "stderr": ""}`. It
writes `{"argv", "stdin", "cwd", "env_has_api_key"}` as JSON to the path in
`FAKE_CLAUDE_RECORD` (when set), sleeps `sleep_s`, prints each event as a JSON line and exits
with `exit_code`. With `--version` it prints `9.9.9 (Claude Code)`.

- [ ] **Step 1: Write the failing tests** (`tests/test_claude_cli.py`). A `scenario(tmp_path,
  monkeypatch, events, **extra)` helper writes the scenario and record paths and sets both
  environment variables. `FAKE = (sys.executable, str(Path(__file__).parent / "fake_claude.py"))`.
  The `init(...)` and `result(...)` helpers build events like the recorded ones:
  `{"type": "system", "subtype": "init", "apiKeySource": "none", "claude_code_version": "9.9.9", "tools": [...]}`
  and `{"type": "result", "subtype": "success", "is_error": false, "stop_reason": "tool_use", "api_error_status": null, "num_turns": 2, "structured_output": {...}, "modelUsage": {"claude-haiku-5-5": {"inputTokens": 2, "outputTokens": 115, "cacheReadInputTokens": 10, "cacheCreationInputTokens": 1099}}}`.
  Tests:
  - `test_build_command_has_the_isolation_flags`: every flag from Global Constraints is
    present; `--json-schema` is compact JSON; `--mcp-config` and `--allowedTools` appear only
    when `mcp_config` is set; the user message is not in argv.
  - `test_run_cli_returns_the_answer_and_summed_tokens`: input = 2 + 1099 + 10, output 115,
    models `("claude-haiku-5-5",)`, version `"9.9.9"`.
  - `test_user_message_goes_on_stdin_not_argv`: a 200 KB message reaches the fake's stdin.
  - `test_api_key_is_removed_from_the_environment`: with `ANTHROPIC_API_KEY` set,
    `env_has_api_key` is false; the cwd is an empty temporary directory, not the test's cwd.
  - `test_errors` (parametrized): `apiKeySource: "ANTHROPIC_API_KEY"` gives
    `ClaudeAuthError`; `api_error_status: 429` gives `ClaudeUsageLimit`; `stop_reason:
    "refusal"` gives `ClaudeRefusal`; `subtype: "error_max_budget_usd"` gives
    `ClaudeRunError` with the subtype in the message; a second model in `modelUsage` gives
    `ClaudeUnexpectedModel`; `structured_output` missing gives `ClaudeNoAnswer`; no result
    event and exit code 3 gives `ClaudeRunError` with the stderr tail.
  - `test_timeout_kills_the_process_group`: the scenario sleeps 30 s and `timeout_s=1` gives
    `ClaudeTimeout` within 10 s; the fake records its pid and the test asserts the process no
    longer exists (`os.kill(pid, 0)` raises `ProcessLookupError`).
  - `test_claude_code_version`: `"9.9.9"` from the fake; `"unknown"` for a missing command.
- [ ] **Step 2: Run them and check they fail:** `uv run pytest tests/test_claude_cli.py -q`
  (expected: ImportError).
- [ ] **Step 3: Implement `claude_cli.py`.** `run_cli` creates a
  `tempfile.TemporaryDirectory(prefix="geoevals-claude-")`, writes `mcp.json` there when
  `mcp_config` is set, copies `os.environ` without `ANTHROPIC_API_KEY` and
  `ANTHROPIC_AUTH_TOKEN`, and starts `subprocess.Popen(build_command(...), cwd=tmp,
  stdin=PIPE, stdout=PIPE, stderr=PIPE, text=True, env=env, start_new_session=True)`. It calls
  `communicate(call.user_message, timeout=call.timeout_s)`; on `TimeoutExpired` it runs
  `os.killpg(proc.pid, signal.SIGKILL)`, reaps the process and raises `ClaudeTimeout`.
  `check_result` checks in this order: a result event exists (else `ClaudeRunError` naming the
  exit code and the last 2,000 chars of stderr), auth, usage limit, refusal, subtype and
  `is_error`, models, answer. Tokens are summed over `modelUsage`.
- [ ] **Step 4: Run the tests and check they pass.**
- [ ] **Step 5: Commit** `feat: run cases through the local Claude Code CLI`.

### Task 2: Prompts and case rendering

**Files:**
- Create: `src/geoevals/leaderboard/prompting.py`,
  `src/geoevals/adapters/prompts/direct_v1.md`, `src/geoevals/adapters/prompts/python_v1.md`
- Test: `tests/test_claude_adapters.py` (prompting section)

**Interfaces:**
- Produces:
  - `PROMPTS_DIR: Path`, `load_template(track: str, version: str) -> str` (raises `ValueError` for an unknown template)
  - `system_prompt(template: str, task_statement: str) -> str` (replaces `{task_statement}`)
  - `spec_for(case_input: Mapping) -> tuple[str, dict]` (task statement and output schema from `benchmark_dir/benchmark.yaml`, cached per directory)
  - `cli_schema(schema: dict) -> dict` (a deep copy without `evidence_type` keys)
  - `direct_message(case_input: Mapping) -> str`
  - `python_message(case_input: Mapping, mount: str = "/bench") -> str`

The direct message holds the prompt, then `Parameters (JSON):` and the params, then for each
file `Input file "<name>" (<relative path>, GeoJSON):` and its text. Parquet files are
converted with `geopandas.read_parquet(path).to_json(drop_id=True)`. The python message gives
`<mount>/<relative path>` for each file in place of the text.

- [ ] **Step 1: Write the failing tests:**
  - `test_direct_message_inlines_geojson_and_withholds_answers` on a real `gis_correctness`
    case (from `load_cases`): the message holds the prompt, the params and the file's
    GeoJSON; it does not hold `"expected"`, the case ID, `"trap"`, or a tolerance key.
  - `test_parquet_inputs_become_geojson` on a `human_context_access` case: each of the three
    files appears as a FeatureCollection whose coordinates equal those of
    `gpd.read_parquet`.
  - `test_python_message_gives_container_paths`: `/bench/fixtures/...` is present and no
    GeoJSON is inlined.
  - `test_cli_schema_drops_evidence_type_only`: the human-context schema loses every
    `evidence_type` and is otherwise equal; the GIS schema is unchanged.
  - `test_templates_exist_and_take_the_task_statement`: both v1 templates contain
    `{task_statement}` once; `load_template("direct", "v9")` raises `ValueError`.
- [ ] **Step 2: Run and check they fail.**
- [ ] **Step 3: Write the templates and `prompting.py`.** The templates say: this is a
  GeoEvals task (task statement); answer only through the structured-output tool following
  its schema; use `ok` when answerable, and otherwise `needs_clarification`,
  `insufficient_data` or `invalid_request` instead of guessing. `python_v1` adds the
  `run_python` tool: Python 3.12 with GeoPandas, Shapely, pyproj, NetworkX and SciPy, no
  network, input files read-only at the given paths, `/tmp` writable, one fresh process per
  call, print what you need.
- [ ] **Step 4: Run and check they pass.**
- [ ] **Step 5: Commit** `feat: prompts and case rendering for Claude adapters`.

### Task 3: Direct adapter and registration

**Files:**
- Create: `src/geoevals/adapters/claude.py`
- Modify: `src/geoevals/adapters/__init__.py` (register 6 adapters), `CHANGELOG.md`
  (Unreleased), `tests/test_docs.py` (`test_changelog_lists_benchmarks_schemas_metrics_and_adapters`
  also accepts adapters listed under `## Unreleased`)
- Test: `tests/test_claude_adapters.py`

**Interfaces:**
- Consumes: Task 1 (`CliCall`, `run_cli`, errors, `claude_code_version`) and Task 2.
- Produces:
  - `MODELS: dict[str, str]` (slug to model ID), `ADAPTER_VERSION = "0.1.0"`
  - `ClaudeAdapterConfig` (pydantic, `extra="forbid"`): `effort="high"`,
    `prompt_version="v1"`, `case_timeout_s=840.0`, `max_case_usd=5.0`, `max_tool_calls=20`,
    `only_cases: list[str] | None = None`, `claude_command: list[str] = ["claude"]`,
    `sandbox_image: str | None = None`
  - `ClaudeDirectAdapter(slug: str)`, `ClaudePythonAdapter(slug: str)`; attributes `name`,
    `version` (`"0.1.0+cc.<version>"`), `model`, `track`, `deterministic = False`
  - Registration: `register_adapter(f"claude_{track}_{slug}", functools.partial(Class, slug))`

`setup` validates the config, loads the template, and raises `RuntimeError` when
`shutil.which(claude_command[0])` is None. `predict` raises `SkipCase` for a case not in
`only_cases`, and for every case once a `ClaudeUsageLimit` has been seen. The direct track
returns `AdapterResponse(output=result.structured_output, tokens=TokenUsage(...))`.

- [ ] **Step 1: Write the failing tests** (using `tests/fake_claude.py` through
  `claude_command`):
  - `test_direct_adapter_returns_answer_and_tokens`, including the `--model` value and the
    system prompt containing the spec's task statement.
  - `test_only_cases_skips_other_cases`.
  - `test_usage_limit_skips_later_cases`: the first call returns 429; this case and the next
    raise `SkipCase("usage limit reached")`, and the fake is called only once.
  - `test_setup_fails_when_the_cli_is_missing`.
  - `test_config_rejects_unknown_keys`.
  - `test_registered_names`: the 6 names are in `registered_adapter_names()` and each factory
    pickles.
  - `test_direct_adapter_in_a_full_run`: `run_benchmark` on `gis_correctness` with
    `only_cases` listing 2 cases and a fake that answers the right expected output for one;
    the result is valid, has 2 scored or invalid cases plus skipped ones, and records tokens.
- [ ] **Step 2: Run and check they fail.**
- [ ] **Step 3: Implement the adapter, the registration, the CHANGELOG entry and the
  docs-test change.**
- [ ] **Step 4: Run** `uv run pytest tests/test_claude_adapters.py tests/test_docs.py -q` and
  check that they pass.
- [ ] **Step 5: Commit** `feat: Claude direct-track adapters`.

### Task 4: Docker sandbox

**Files:**
- Create: `src/geoevals/leaderboard/sandbox.py`, `src/geoevals/leaderboard/sandbox.Dockerfile`
- Modify: `pyproject.toml` (marker `docker`; `addopts` gains `-m "not network and not docker"`)
- Test: `tests/test_sandbox.py`

**Interfaces:**
- Produces:
  - `MOUNT = "/bench"`
  - `ExecResult(exit_code: int, stdout: str, stderr: str, timed_out: bool)`
  - `repo_root() -> Path` (holds `uv.lock`, else `RuntimeError`)
  - `image_tag(root: Path) -> str` (`geoevals-sandbox:<12 hex>` from `uv.lock` and the Dockerfile)
  - `ensure_image(root: Path | None = None) -> str` (builds when missing)
  - `docker_available() -> bool`
  - `start_container(image: str, name: str, fixtures: Path | None) -> None`
  - `exec_python(name: str, code: str, timeout_s: float = 60, max_output: int = 20_000) -> ExecResult`
  - `remove_container(name: str) -> None` (never raises)
  - `truncate(text: str, limit: int) -> str`

The image is `python:3.12-slim` with `pip install --require-hashes -r requirements.txt` from
`uv export --frozen --no-dev --extra network --no-emit-project`, and `USER 65534:65534`.
Containers run `sleep infinity` with the flags in Global Constraints, `--memory 2g --cpus 2
--pids-limit 256`, `-e HOME=/tmp -e MPLCONFIGDIR=/tmp -w /bench` and the label
`geoevals.sandbox=1`. `exec_python` runs `docker exec -i <name> timeout -s KILL <s> python -`
with the code on stdin.

- [ ] **Step 1: Write the failing tests.** Unit tests: `truncate` keeps the head and adds a
  marker; `image_tag` changes when `uv.lock` changes (copied to `tmp_path`). Docker tests
  (`@pytest.mark.docker`, skipped when `docker_available()` is false, with the plain
  `python:3.12-slim` image): `test_sandbox_isolation` (a socket connection fails; writing
  under `/bench/fixtures` fails; `/bench` lists only `fixtures`; `/tmp` is writable; the user
  is not root); `test_exec_timeout` (`time.sleep(10)` with `timeout_s=2` gives `timed_out`);
  `test_exec_output_limit`; `test_remove_container` (the container is gone afterwards).
- [ ] **Step 2: Run** `uv run pytest tests/test_sandbox.py -m docker -q` and check they fail.
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Run the unit and docker tests, then build the real image once with**
  `uv run python -c "from geoevals.leaderboard.sandbox import ensure_image; print(ensure_image())"`
  **and check that `import geopandas, networkx, scipy` works in it.**
- [ ] **Step 5: Commit** `feat: Docker sandbox for the python track`.

### Task 5: Sandbox MCP server

**Files:**
- Create: `src/geoevals/leaderboard/sandbox_mcp.py`
- Test: `tests/test_sandbox.py` (MCP section)

**Interfaces:**
- Consumes: Task 4 (`ExecResult`, `start_container`, `exec_python`, `remove_container`).
- Produces:
  - `TOOL_NAME = "run_python"`
  - `SandboxServer(execute: Callable[[str], ExecResult], max_calls: int)` with
    `handle(message: dict) -> dict | None`
  - `main(argv: Sequence[str] | None = None) -> int` with `--image`, `--fixtures`, `--name`,
    `--max-calls`, `--timeout-s` and `--max-output`; it starts the container lazily and
    removes it at EOF

- [ ] **Step 1: Write the failing tests:** `initialize` echoes the protocol version and
  advertises tools; notifications get no reply; `tools/list` has `run_python` with a required
  string `code`; `tools/call` returns the formatted exit code, stdout and stderr, with
  `isError` for a non-zero exit or a timeout; call `max_calls + 1` returns `isError` with
  "Submit your answer" and does not execute; an unknown method gives JSON-RPC error `-32601`;
  `test_mcp_main_over_stdio` runs `python -m geoevals.leaderboard.sandbox_mcp` with
  `initialize`, `tools/list` and EOF, without Docker, because the container is started lazily.
- [ ] **Step 2: Run and check they fail.**
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Run and check they pass.**
- [ ] **Step 5: Commit** `feat: stdio MCP server for sandboxed run_python`.

### Task 6: Python adapter

**Files:**
- Modify: `src/geoevals/adapters/claude.py`
- Test: `tests/test_claude_adapters.py`

**Interfaces:**
- Consumes: Tasks 1 to 5.
- Produces: `ClaudePythonAdapter.predict`, `trajectory_from_events(events: list[dict]) -> list[dict]`

`setup` also checks `docker_available()` (else `RuntimeError`) and resolves `sandbox_image`
(`ensure_image()` when it is None). `predict` names the container
`geoevals-<uuid4 hex[:12]>` and passes `mcp_config = {"mcpServers": {"sandbox": {"command":
sys.executable, "args": ["-m", "geoevals.leaderboard.sandbox_mcp", ...]}}}` and
`allowed_tools=("mcp__sandbox__run_python",)`. It calls `remove_container` in `finally`.
`trajectory_from_events` makes one step per `tool_use` block: `mcp__sandbox__run_python`
becomes tool `run_python` with args `{"code": ...}`; `StructuredOutput` becomes tool `None`
with args `{}`. The status comes from the matching `tool_result`'s `is_error`;
`error_message` is the first 500 characters of its text when it is an error;
`duration_s`/`tokens` are None.

- [ ] **Step 1: Write the failing tests:**
  - `test_python_adapter_passes_the_mcp_server_and_paths` (fake CLI; the recorded argv has
    `--mcp-config` and `--allowedTools mcp__sandbox__run_python`; stdin has
    `/bench/fixtures/`).
  - `test_trajectory_from_events` (two run_python calls, one failing, then StructuredOutput;
    the steps are numbered 0 to 2 and `trajectory_problem` returns None).
  - `test_python_adapter_removes_the_container_on_error` (monkeypatched `remove_container`
    is called when the fake times out).
  - `test_python_setup_fails_without_docker` (monkeypatched `docker_available`).
- [ ] **Step 2: Run and check they fail.**
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Run and check they pass.**
- [ ] **Step 5: Commit** `feat: Claude python-track adapters`.

### Task 7: Leaderboard table and CLI

**Files:**
- Create: `src/geoevals/leaderboard/table.py`
- Modify: `src/geoevals/cli.py` (`leaderboard add <run_dir> [--results]`,
  `leaderboard build [--results] [--readme] [--check]`), `README.md` (a `## Leaderboard`
  section with the markers, after "Available benchmarks"), `tests/test_docs.py`
- Test: `tests/test_leaderboard.py`

**Interfaces:**
- Produces:
  - `START = "<!-- leaderboard:start -->"`, `END = "<!-- leaderboard:end -->"`,
    `DEFAULT_RESULTS = Path("leaderboard/results")`
  - `LeaderboardError(ValueError)`
  - `Row` dataclass: `benchmark, benchmark_version, manifest_hash, model, track, success, ci_low, ci_high, cases, not_scored, latency_p50_s, latency_p90_s, tokens_in, tokens_out, claude_code, prompt_version, effort`
  - `load_rows(results_dir: Path) -> list[Row]` (raises `LeaderboardError` for a run with skipped cases, an adapter that is not a Claude leaderboard adapter, or incomparable runs within a benchmark)
  - `render(rows: list[Row]) -> str`
  - `update_readme(text: str, table: str) -> str` (raises `LeaderboardError` without the markers)
  - `add_run(run_dir: Path, results_dir: Path) -> Path`

- [ ] **Step 1: Write the failing tests** with fixture results made by `_result(...)` (a
  minimal dict with the fields read: `benchmark`, `adapter`, `dataset_manifest_hash`,
  `summary_metrics.task_success`, `efficiency`, `cases[].status`):
  `test_render_sorts_and_formats` (benchmark, then track, then Opus/Sonnet/Haiku; success
  `0.750 (0.62–0.85)`; tokens with thousands separators); `test_render_with_no_runs`;
  `test_build_rejects_runs_with_skipped_cases`; `test_build_rejects_incomparable_runs`;
  `test_update_readme_replaces_only_between_markers`; `test_add_run_copies_result_and_config`;
  `test_cli_build_check` (exit 1 when stale, 0 after writing).
  In `tests/test_docs.py`: `test_readme_leaderboard_is_up_to_date` runs
  `main(["leaderboard", "build", "--check"])` from the repository root and expects 0.
- [ ] **Step 2: Run and check they fail.**
- [ ] **Step 3: Implement `table.py`, the CLI commands and the README section** (generated
  with `uv run geoevals leaderboard build`).
- [ ] **Step 4: Run** `uv run pytest -q` **and check that the full suite passes.**
- [ ] **Step 5: Commit** `feat: generated leaderboard table in the README`.

### Task 8: Configs and documentation

**Files:**
- Create: `leaderboard/configs/direct.yaml`, `python.yaml`, `pilot-direct.yaml`,
  `pilot-python.yaml`, `leaderboard/README.md`, `leaderboard/results/.gitkeep`
- Modify: `ROADMAP.md` (LLM adapters and leaderboard items), `docs/reproducibility.md`
  (`## Leaderboard runs`), `docs/data-governance.md` (a note in "Secrets and personal data":
  case inputs go to Anthropic through Claude Code; no credentials are stored), `.gitignore`
  (nothing new is needed if `runs/` is already ignored; check), `tests/test_docs.py` (add
  `leaderboard/README.md` to the spelling check)

The configs have `split: test`, `seed: 0`, `timeout_s: 900`, `max_retries: 0`, `workers: 1`
and `adapter: {effort: high, prompt_version: v1, case_timeout_s: 840, max_case_usd: 5}`, plus
`max_tool_calls: 20` on python. The pilot configs add `only_cases` with five cases per
benchmark: `crs_transform-001`, `distance-003`, `buffer-001`, `spatial_join-005`,
`abstention-001`, `nearest_amenity-001`, `amenity_count-001`, `network_detour-001`,
`open_amenities-001` and the first human-context abstention case. Check each ID exists.

- [ ] **Step 1: Write** `test_leaderboard_configs_are_valid` (every config parses with
  `load_run_config`, the adapter part validates as `ClaudeAdapterConfig`, `case_timeout_s <
  timeout_s`, and every pilot ID is a real case ID).
- [ ] **Step 2: Run and check it fails.**
- [ ] **Step 3: Write the configs and docs.**
- [ ] **Step 4: Run the full checks:** `uv run ruff check . && uv run ruff format --check . &&
  uv run pyright && uv run pytest -q`.
- [ ] **Step 5: Commit** `docs: leaderboard configs, runbook and documentation`.

### Task 9: Pilot

- [ ] Run the Opus 5.5 pilot on both benchmarks and both tracks:
  `uv run geoevals run --benchmark benchmarks/<dir>/benchmark.yaml --adapter
  claude_<track>_opus_5_5 --config leaderboard/configs/pilot-<track>.yaml --out runs/pilot`.
- [ ] Report to the user the measured wall time and tokens per case, the statuses, and any
  harness problems. Full runs start only after the user agrees, because they use the
  subscription's limits.

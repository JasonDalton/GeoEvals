"""GPT-6 Luna via the user's Codex subscription, using the existing benchmark tracks."""

import subprocess
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from geoevals.adapters.base import AdapterResponse, SkipCase
from geoevals.leaderboard import prompting, sandbox
from geoevals.leaderboard.codex_cli import CodexHarnessError, CodexUsageLimit, run_case
from geoevals.leaderboard.sandbox_mcp import format_result


class CodexAdapterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    effort: Literal["low", "medium", "high", "max"] = "high"
    prompt_version: str = Field(default="v1", pattern=r"^v[0-9]+$")
    case_timeout_s: float = Field(default=840.0, gt=0, allow_inf_nan=False)
    max_tool_calls: int = Field(default=20, ge=1)
    only_cases: list[str] | None = None
    sandbox_image: str | None = None
    telemetry_path: str | None = None


class CodexDirectAdapter:
    track: ClassVar[str] = "direct"
    name = "codex_direct_luna"
    version = "0.1.1"
    deterministic = False

    def __init__(self) -> None:
        version = (
            subprocess.run(
                ["codex", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            .stdout.strip()
            .removeprefix("codex-cli ")
        )
        self.version = f"0.1.1+codex.{version}"
        self._cli_version = version

    def setup(self, config: Mapping[str, Any]) -> None:
        self._config = CodexAdapterConfig.model_validate(dict(config))
        self._template = prompting.load_template(self.track, self._config.prompt_version)
        self._blocked: str | None = None
        self._image: str | None = None
        if self.track == "python":
            self._image = self._config.sandbox_image or sandbox.ensure_image()

    def predict(self, case_input: Mapping[str, Any]) -> AdapterResponse:
        if (
            self._config.only_cases is not None
            and case_input["case_id"] not in self._config.only_cases
        ):
            raise SkipCase("not in only_cases")
        if self._blocked:
            raise SkipCase(self._blocked)
        statement, schema = prompting.spec_for(case_input)
        name = f"geoevals-codex-{uuid.uuid4().hex[:12]}"
        started = False

        def execute(code: str) -> tuple[str, bool]:
            nonlocal started
            try:
                if not started:
                    assert self._image is not None
                    fixtures = Path(case_input["benchmark_dir"]) / "fixtures"
                    sandbox.start_container(
                        self._image, name, fixtures if fixtures.is_dir() else None
                    )
                    started = True
                result = sandbox.exec_python(name, code)
            except (sandbox.SandboxError, OSError, subprocess.SubprocessError) as exc:
                raise CodexHarnessError(f"Python sandbox failed: {exc}") from exc
            return format_result(result), result.exit_code == 0 and not result.timed_out

        python = self.track == "python"
        try:
            return run_case(
                system_prompt=prompting.system_prompt(self._template, statement).replace(
                    "structured-output tool", "submit_answer tool"
                ),
                user_message=(prompting.python_message if python else prompting.direct_message)(
                    case_input
                ),
                schema=prompting.cli_schema(schema),
                effort=self._config.effort,
                timeout_s=self._config.case_timeout_s,
                execute=execute if python else None,
                max_tool_calls=self._config.max_tool_calls,
                container=name if python else None,
                telemetry_path=Path(self._config.telemetry_path)
                if self._config.telemetry_path
                else None,
                case_id=str(case_input["case_id"]),
                expected_cli_version=self._cli_version,
            )
        except CodexUsageLimit as exc:
            self._blocked = str(exc)
            raise SkipCase(str(exc)) from exc
        except CodexHarnessError as exc:
            self._blocked = f"harness failed; remaining cases stopped: {exc}"
            raise
        finally:
            if started:
                sandbox.remove_container(name)

    def teardown(self) -> None:
        pass


class CodexPythonAdapter(CodexDirectAdapter):
    track = "python"
    name = "codex_python_luna"

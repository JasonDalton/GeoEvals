"""A stand-in for the ``claude`` CLI in tests: replays a scenario and records how it was called.

The scenario is the JSON file named by ``FAKE_CLAUDE_SCENARIO``::

    {"events": [...], "exit_code": 0, "sleep_s": 0, "stderr": ""}

When ``FAKE_CLAUDE_RECORD`` names a file, the call is recorded there as JSON: ``argv``, ``stdin``,
``cwd``, ``cwd_entries`` (the files in the working directory at start), ``env_has_api_key`` and
``pid``. Then the fake sleeps ``sleep_s``, prints each event as one JSON line and exits with
``exit_code``. ``--version`` prints a fixed version.
"""

import json
import os
import sys
import time


def main() -> int:
    if sys.argv[1:] == ["--version"]:
        print("9.9.9 (Claude Code)")
        return 0
    with open(os.environ["FAKE_CLAUDE_SCENARIO"], encoding="utf-8") as file:
        scenario = json.load(file)
    sequence = scenario.get("sequence")
    if sequence is not None:
        counter = os.environ["FAKE_CLAUDE_SCENARIO"] + ".count"
        calls = 0
        if os.path.exists(counter):
            with open(counter, encoding="utf-8") as file:
                calls = int(file.read())
        with open(counter, "w", encoding="utf-8") as file:
            file.write(str(calls + 1))
        scenario = sequence[min(calls, len(sequence) - 1)]
    stdin = sys.stdin.read()
    record_path = os.environ.get("FAKE_CLAUDE_RECORD")
    if record_path:
        record = {
            "argv": sys.argv[1:],
            "stdin": stdin,
            "cwd": os.getcwd(),
            "cwd_entries": sorted(os.listdir(".")),
            "env_has_api_key": "ANTHROPIC_API_KEY" in os.environ,
            "env": {
                k: v
                for k, v in os.environ.items()
                if k.startswith(("ANTHROPIC", "CLAUDE", "DISABLE"))
            },
            "ppid": os.getppid(),
            "pid": os.getpid(),
        }
        records = []
        if os.path.exists(record_path):
            with open(record_path, encoding="utf-8") as file:
                records = json.load(file)
        records.append(record)
        with open(record_path, "w", encoding="utf-8") as file:
            json.dump(records, file)
    time.sleep(scenario.get("sleep_s", 0))
    for event in scenario.get("events", []):
        print(json.dumps(event), flush=True)
    sys.stderr.write(scenario.get("stderr", ""))
    return scenario.get("exit_code", 0)


if __name__ == "__main__":
    sys.exit(main())

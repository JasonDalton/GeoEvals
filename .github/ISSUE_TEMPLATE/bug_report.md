---
name: Bug report
about: Something in GeoEvals does not work as documented
title: "bug: "
labels: bug
---

<!-- Report security vulnerabilities privately (see SECURITY.md), not here. -->

## What happened

<!-- What you did, what you expected, and what happened instead. -->

## Steps to reproduce

```sh
# The exact commands, from a clean clone
uv sync
uv run geoevals ...
```

## Output

<!-- The full error message or traceback, or the case IDs and metric values that are wrong. -->

```text

```

## Environment

- GeoEvals version or commit (`uv run geoevals --version`, `git rev-parse HEAD`):
- OS and CPU architecture:
- Python version:
- Benchmark ID and version, adapter name and version (if the bug is in a run):

<!--
If the bug is in a run, attach result.json or paste its `environment` block: it has the
GEOS and PROJ versions and the uv.lock hash. Do not attach restricted data from data/raw/.
-->

## Is a score affected?

- [ ] Yes, a published score or baseline is wrong because of this bug
- [ ] No, or I don't know

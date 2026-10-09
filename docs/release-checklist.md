# Release checklist

This is the release acceptance checklist from Section 10 of the kickoff plan, for GeoEvals
v0.1.0. Every item is P0 (a release blocker). Each item has one status:

- **`automated`**: a CI job in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
  verifies it. The job is named by its ID (`check`, `reproduce`, `package` or `secrets`). The
  item passes when that job is green on the release commit.
- **`human sign-off required`**: a person must review it and sign below. CI gives evidence
  but cannot decide it. There are three reviews: the license compatibility review, the privacy
  review and the final scope approval.

`tests/test_docs.py` checks that this file keeps all 12 items, that each has a status, and
that each automated item names a job that exists in the CI workflow.

## Checklist

| # | Item | Status | Verified by | Evidence |
| --- | --- | --- | --- | --- |
| 1 | Repository purpose, scope, and intended users are clear. | human sign-off required | final scope approval | README sections "What GeoEvals evaluates, and why" and "Three pillars"; [`principles.md`](principles.md); the non-goals in the PRD. `check` (Pytest) only checks that the documents exist. |
| 2 | License and attribution obligations are clear for code and every included dataset. | human sign-off required | license compatibility review | [`LICENSE`](../LICENSE) (MIT); the license inventory in [`datasets/README.md`](../datasets/README.md); [`dependency-licenses.md`](dependency-licenses.md); the License section of each benchmark card. `check` fails on a stale inventory ("License inventory is up to date") and on a GPL or AGPL runtime dependency ("Dependency license report"). |
| 3 | No credentials, private traces, or restricted data are present in history or release artifacts. | human sign-off required | privacy review | `secrets` scans the full git history with gitleaks. `check` ("Validate benchmark specs and dataset manifests") fails when an asset marked `redistributable: false` is tracked. The reviewer also lists the sdist and wheel that `package` builds (`tar tzf`, `unzip -l`). |
| 4 | Clean install and documented quickstart succeed on a supported environment. | automated | `package`, `check`, `reproduce` | `package` installs the built wheel into a fresh venv and runs `geoevals --version` and the smoke benchmark. `check` (Pytest, `test_readme_quickstart_runs_verbatim`) runs the README quickstart. `reproduce` installs from `uv.lock` with no cache. |
| 5 | All schemas validate and all automated tests pass. | automated | `check` | Steps "Pytest", "Validate benchmark specs and dataset manifests", "Validate CITATION.cff", and "Smoke report" (validates the smoke run's `result.json`). |
| 6 | At least one benchmark runs end to end with a baseline and reference outputs. | automated | `reproduce`, `check` | `reproduce` reruns every published baseline in `baselines/` and compares it with the committed result. `check` (Pytest) checks that the committed reference outputs match the reference workflows. |
| 7 | Metrics are defined precisely, including units, edge cases, and aggregation behavior. | automated | `check` | Pytest: `test_every_registered_metric_is_documented` requires a section in [`metrics.md`](metrics.md) for every registered metric, and the metric tests cover units, edge cases and aggregation. |
| 8 | Results include model/data/config versions, failures, and limitations. | automated | `check`, `reproduce` | The run-result schema requires them; `check` validates the smoke result and the report snapshots, and Pytest `test_baseline_report_states_model_adapter_manifest_and_limitations` checks every published report. `reproduce` checks the committed results. |
| 9 | Geographic and temporal leakage risks are documented and addressed for the claims made. | human sign-off required | final scope approval | The split strategy and leakage controls in each benchmark card and spec ([`best-practices.md`](best-practices.md), "Split integrity"). v0.1.0 uses synthetic fixtures and makes no claim of transfer to new places or times. |
| 10 | README includes a reproducible example, citation instructions, contribution path, and roadmap. | automated | `check` | Pytest: `test_readme_has_citation_contributing_and_roadmap` and `test_readme_quickstart_runs_verbatim`. |
| 11 | Known limitations and unsupported use cases are explicit. | automated | `check` | Pytest: `test_every_benchmark_has_a_dataset_card` requires the "Limitations", "Intended uses" and "Prohibited uses" sections; every report has a "Limitations" section. |
| 12 | A versioned release and changelog are prepared. | automated | `check`, `package` | Pytest: `test_release_version_is_consistent` (`pyproject.toml`, `CITATION.cff` and the latest [`CHANGELOG.md`](../CHANGELOG.md) entry agree, and [`ROADMAP.md`](../ROADMAP.md) exists). `package` checks that the installed wheel reports the same version. |

## Human sign-off

| Review | Items | Reviewer | Date | Result |
| --- | --- | --- | --- | --- |
| License compatibility review | 2 | | | |
| Privacy review | 3 | | | |
| Final scope approval | 1, 9 | | | |

## After sign-off (maintainer only)

The release preparation creates no git tag, uploads nothing to PyPI and publishes no GitHub
release. After every automated item is green on the release commit and every review above is
signed:

1. Set the date of the `0.1.0` entry in `CHANGELOG.md` to the release date, and add the version
   links once the repository is hosted.
2. Optionally regenerate the published baselines: their environment fingerprints record
   `geoevals_version` `0.1.0.dev0`, the version that produced them. `geoevals reproduce` does
   not compare the environment, so they reproduce either way.
3. Tag the release commit (`git tag -a v0.1.0`) and push the tag.
4. Publish the GitHub release with the `0.1.0` changelog entry and the `uv build` artifacts.
5. If the project publishes to PyPI (open question 4 in the PRD), upload the same artifacts.

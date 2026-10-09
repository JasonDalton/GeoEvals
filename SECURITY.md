# Security policy

## Report a vulnerability

Do not report security vulnerabilities in a public issue, discussion or pull request.

Report them privately through GitHub Security Advisories:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Describe the problem, the affected version or commit, the steps to reproduce it and the
   impact you expect.

Only the maintainers can see the report. We work with you on the fix in a private advisory,
and publish the advisory, with credit to you if you want it, when a fixed release is
available.

GitHub documents the process in
[Privately reporting a security vulnerability](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability).

## Supported versions

GeoEvals is before 1.0. Only the latest release and the `main` branch get security fixes.

## Scope

Examples of problems we want to hear about:

- Code execution or file writes outside the run directory from a crafted benchmark spec,
  case file, dataset manifest, run config or run result
- Path traversal through paths in a spec, a manifest or a case
- A way for `geoevals data fetch` or validation to commit, or fail to flag, data that a
  manifest marks `redistributable: false`
- Credentials or personal data in the repository, a published baseline or a run artifact

Adapters run the code of the system under evaluation. Running an untrusted adapter or an
untrusted `reference.py` is equal to running untrusted code, and is not a vulnerability in
GeoEvals.

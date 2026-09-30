# FAQ

**Does this make me EU AI Act compliant?**
No, and it never claims to. `aibom` produces inventory and evidence — the
answer to "what does this AI system actually use?". Compliance is a conclusion a
human draws from evidence. See [framework-mapping.md](framework-mapping.md).

**Does it phone home?**
No. `aibom generate`, `validate`, `render`, `diff` and `explain-risk` make no
network calls at all. The only command that touches the network is `attest`,
which publishes a digest to the sigstore transparency log — and only when you
run it explicitly.

**Where do the facts come from?**
Three places, in order: the `surface.lock` produced by the scanner, then
`aibom.yaml` for what code cannot reveal, then `CODEOWNERS` and git metadata.
Anything still missing appears as a review note rather than a silent gap.

**What if I don't have a `surface.lock`?**
`aibom` runs the scanner in-process and prints which path it used. `--refresh`
forces a rescan even when a lock exists.

**Why is my tool "high risk"?**
Run `aibom explain-risk <tool>`. It prints the rule ids that fired, the field
each matched, and the evidence snippet. Every verdict is a regex in
`capabilities.yaml` that you can read and challenge.

**I disagree with the heuristic.**
Override it in `aibom.yaml` under `tools.<name>`. The BOM then records *both*
verdicts: `aibom:heuristic_risk` keeps the rulebook's, `aibom:risk` becomes
yours, and `aibom:risk_override: true` plus `justification` show an auditor that
a human decided. Review notes warn when an override has no justification.

**Why does the digest ignore the timestamp and serial number?**
Because they change on every run and say nothing about the AI surface. Ignoring
them makes the digest a stable fingerprint of the *content* — that is what makes
`diff` cheap and attestation meaningful. Change one prompt and the digest
changes.

**Can I merge this with my existing SBOM?**
Yes: `aibom generate --merge-sbom sbom.cdx.json`. The output carries both the
software and the AI components under one `metadata.component`, so a single
upload to Dependency-Track covers both.

**What's in `compositions[]`?**
The honest completeness statement. Scanned kinds are `complete` when
`surface.lock` is fresh, `incomplete` when it has drifted. Manifest-declared
kinds stay `unknown` unless you set `complete: <kind>: true`. Under-claiming is
safe; over-claiming is what an auditor finds.

**Is signing automatic?**
No. `generate` never signs. Run `aibom attest` when you mean it — signing
publishes the digest to the public transparency log.

**Which Python versions?**
3.11 and newer. The tool is typed and mypy-clean.

**How do I contribute?**
The compounding assets are data-only: new MCP package classifications in
`mcp-packages.yaml`, new rules in `capabilities.yaml`, and framework-mapping
rows. Each is a small, reviewable YAML or Markdown diff. `docs/risk-rules.md` is
generated from the YAML, so it can never drift from the code that runs.

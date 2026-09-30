# Changelog

All notable changes to `aibom` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-09-30

The first release. Everything below is new.

### Added
- **`aibom generate`** — produce a CycloneDX 1.6 AI BOM from a repository:
  models (with model cards), prompts, tools with blast-radius, MCP servers,
  datasets, AI SDK versions, provider APIs and declared external AI services.
- **Stable content digest** — SHA-256 over the BOM with `serialNumber`,
  `metadata.timestamp` and `version` removed, written to `<out>.sha256` and
  printed in the Markdown footer.
- **`aibom validate`** — re-validate against the vendored CycloneDX 1.6 schema
  and check the content digest, plus ingestion-friendliness checks.
- **`aibom render`** — regenerate Markdown/HTML/PDF from a BOM, so the JSON is
  the source of truth.
- **`aibom diff`** — added/removed/changed per component kind, with
  `--fail-on risk-increase|new-high-risk|new-provider` gates and
  release-note-ready Markdown.
- **`aibom explain-risk`** — print the rule ids that fired, the field matched
  and the evidence, so every verdict is auditable.
- **Transparent capability rulebook** — `capabilities.yaml` with a versioned
  `rules_version`, plus `mcp-packages.yaml` with 40+ curated MCP packages.
- **Review notes** — floating aliases, retired models, high-risk tools without
  human oversight, MCP over plain HTTP, unpinned MCP packages, unowned prompts,
  PII datasets without consent basis or retention, models without purpose.
  `--strict` turns error-level notes into a non-zero exit.
- **`aibom attest` / `aibom verify`** — keyless sigstore signing via cosign or
  `sigstore-python`, with a digest fallback. No network calls anywhere else.
- **`aibom manifest validate`** and **`aibom init`** — schema validation with
  line-numbered errors, and a commented example manifest.
- **`aibom doctor`** — environment and input diagnostics.
- **Inputs** — `surface.lock` via the scanner with an in-process fallback,
  `aibom.yaml`, `CODEOWNERS` (GitHub matching semantics), git metadata, AI SDK
  lockfiles, and `--merge-sbom` to fold in an existing software SBOM.
- **Human outputs** — print-optimised single-file HTML with a table of contents,
  Markdown report, and PDF via the `[pdf]` extra.
- **Integrations** — a GitHub composite action, a release workflow with a sticky
  PR diff comment, a pre-commit hook, and Dependency-Track/GUAC ingestion.
- **Python API** — `generate`, `diff`, `render_markdown`, `validate_bom`.
- **Docs** — quickstart, mapping table, manifest reference, generated risk-rules
  page, release integration, signing, and a neutral framework-mapping table with
  an explicit "evidence, not compliance" disclaimer.

### Notes
- Python 3.11+.
- Core dependencies are `pyyaml` and `jsonschema`; the scanner is an optional
  extra (`aibom[scanner]`) with a bundled fallback.
- SPDX 3.0 AI/Dataset profile export, AI advisories, policy-as-code and
  org-level roll-up are on the post-0.1 backlog.

[Unreleased]: https://github.com/modelsurface/aibom/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/modelsurface/aibom/releases/tag/v0.1.0

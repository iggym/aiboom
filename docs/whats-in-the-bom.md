# What's in the BOM

Every AI surface `aibom` finds is mapped to a CycloneDX 1.6 construct. The
mapping is stable and versioned; this page is the reference an auditor reads.

| Source | CycloneDX | Key fields |
| --- | --- | --- |
| **model** | `machine-learning-model` | `name` = pinned snapshot, `version` parsed from the snapshot, `supplier`, `modelCard{modelParameters{task, architectureFamily}, considerations{useCases, technicalLimitations, ethicalConsiderations}, quantitativeAnalysis (eval refs)}`, `externalReferences` (provider docs), `licenses`, and properties `aibom:alias, resolved, floating, kind, locations, deprecation, retirement, price_in_per_1m, price_out_per_1m, context_window, hosting_region, data_processing_agreement, training_data_optout, purpose` |
| **prompt** | `data` with `data[{type: configuration, classification: prompt}]` | `hashes[SHA-256]`, `version` = sha prefix, properties `path, line, approx_tokens, source, owners` |
| **tool** | `library` | `hashes`, `description`, properties `path, source, param_keys, capabilities[], risk, human_in_the_loop, rate_limited, reversible` |
| **dataset** (manifest) | `data` with `data[{type: dataset, classification, sensitiveData[], governance{owners, custodians}}]` | properties `source, retention, jurisdiction, pii, consent_basis, refresh` |
| **ai-sdk** (from lockfiles) | `library` with `purl` | `aibom:role=ai-sdk` |
| **MCP server** | `services[]` | `endpoints`, `authenticated`, `x-trust-boundary`, `data[{flow, classification}]`, properties `transport, command, args, env_keys, config, capabilities, risk, sha256, version_pinned` |
| **provider API** | `services[]` | one per provider present; `data[{flow: bi-directional, classification: <system data_classification>}]`, properties `region`, `dpa` |
| **declared external AI service** (manifest) | `services[]` | as declared |

## Dependencies

- The application depends on every component and service.
- A tool depends on an MCP server when the tool's `source` is that server.
- A model depends on a prompt when both appear in the same file — best-effort,
  and marked `aibom:inferred=true` so an auditor can see which edges are guesses.

## Compositions

`compositions[]` records how complete the inventory is:

- Scanned kinds are `aggregate: complete` when `surface.lock` is fresh
  (`surfacelock check` reports no drift), otherwise `incomplete` with a note.
- Manifest-declared kinds are `unknown` unless the manifest sets
  `complete: <kind>: true`.

This is the field that answers "did you look everywhere?" honestly.

## The stable content digest

`aibom` computes a SHA-256 over the BOM with `serialNumber`,
`metadata.timestamp` and `version` removed. It is written to `<out>.sha256`,
used by `diff` and `validate`, and printed in the Markdown provenance footer.
Two runs over unchanged code produce the same digest; change one prompt and the
digest changes, and `diff` shows exactly one change.

## Properties namespace

All AI-specific facts live under the `aibom:` property prefix so a plain SBOM
tool ignores them and an AI-aware tool can read them:

| Property | Meaning |
| --- | --- |
| `aibom:kind` | `foundation` / `embedding` / … for models |
| `aibom:role` | `ai-sdk`, `model-provider`, `external-ai-service`, … |
| `aibom:risk` | `high` / `medium` / `low` / `unknown` |
| `aibom:capabilities` | comma-separated capability labels |
| `aibom:risk_override` | `true` when a human overrode the heuristic |
| `aibom:heuristic_risk` | what the rulebook alone concluded |
| `aibom:matched_rules` | the rule ids that fired |
| `aibom:inferred` | `true` for best-effort dependency edges |
| `aibom:rules_version` | the rulebook version used (on the BOM metadata) |

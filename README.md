<div align="center">

<img src="docs/assets/logo.svg" alt="aibom" width="120" height="120">

# aibom

### An audit-ready AI Bill of Materials from your repo, in one command.

**Models · prompts · tools with blast-radius · MCP servers · datasets — as a signed, diffable CycloneDX 1.6 document.**

[![CI](https://github.com/modelsurface/aibom/actions/workflows/ci.yml/badge.svg)](https://github.com/modelsurface/aibom/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/aibom?color=7c3aed&label=pypi)](https://pypi.org/project/aibom/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-3776ab?logo=python&logoColor=white)](https://www.python.org/)
[![CycloneDX 1.6](https://img.shields.io/badge/CycloneDX-1.6-6d28d9)](https://cyclonedx.org/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-16a34a)](LICENSE)
[![Signed with sigstore](https://img.shields.io/badge/signed-sigstore-0ea5e9)](docs/signing.md)

```
  █████  ██ ██████   ██████  ███    ███
 ██   ██ ██ ██   ██ ██    ██ ████  ████
 ███████ ██ ██████  ██    ██ ██ ████ ██
 ██   ██ ██ ██   ██ ██    ██ ██  ██  ██
 ██   ██ ██ ██████   ██████  ██      ██
```

**What does this AI system actually use — right now, and what changed since last release?**

</div>

---

## 🎯 The problem

Procurement questionnaires, SOC 2 / ISO 42001 auditors, internal AI governance
boards and the EU AI Act's transparency obligations all ask for the same
inventory:

> *Which models, prompts, tools, MCP servers and datasets does this system use,
> who owns them, how risky are they, and did that change?*

Today it's assembled by hand in a spreadsheet, takes days, and is stale within a
week. Security teams already ingest SBOMs — nobody gives them the AI layer in
the same pipeline.

`aibom` closes that gap.

---

## ⚡ Quickstart

```bash
pip install aibom
aibom generate . --markdown AIBOM.md --html AIBOM.html
```

```
aibom 0.1.0 — audit-ready AI Bill of Materials (CycloneDX 1.6, rules 2026.09.1)
  · root /repo/support-agent
  · input: read surface.lock
  · manifest: /repo/support-agent/aibom.yaml
  · git: main @ e26f46b (clean)
  · inventory: 3 model(s) · 2 prompt(s) · 4 tool(s) · 2 MCP server(s)
               1 provider(s) · 2 dataset(s) · 1 external service(s) · 5 AI SDK(s)
✓ wrote /repo/support-agent/aibom.cdx.json
✓ wrote /repo/support-agent/aibom.cdx.json.sha256
✓ wrote /repo/support-agent/AIBOM.md

review notes: 2 error(s), 3 warning(s), 2 info
  ✗ model.retired             Model `gpt-4.1-2024-08-06` retired on 2026-02-01.
  ✗ tool.high_risk_no_hitl    High-risk tool `delete_customer_account` has no human in the loop.
  ! model.floating            Model alias `gpt-4.1` is not pinned to a dated snapshot.
  ! mcp.unpinned_package      MCP server uses unpinned package `@modelcontextprotocol/server-filesystem`.
  · dataset.no_owner          Dataset `help-center-index` has no owner.

digest: 2cf89618a345d1a464292cada8a680ddbc6550d5f1a8d4e8a131fa2198fd524f
```

Two files land in your repo: `aibom.cdx.json` (machine-readable, CycloneDX 1.6)
and its stable `.sha256` digest. Add `--markdown` for the human report.

**[Full quickstart →](docs/quickstart.md)**

---

## 🧭 What lands in the BOM

<div align="center">

| 🎛️ Found | 📦 CycloneDX | 🔎 Why it matters |
| :--- | :--- | :--- |
| **Models** | `machine-learning-model` + `modelCard` | pinned? retiring? purpose, region, DPA, evals |
| **Prompts** | `data` (`classification: prompt`) | hash, owner, token estimate, exact file:line |
| **Tools** | `library` + blast-radius | `financial` `destructive` `code-exec` … with a readable rule |
| **MCP servers** | `services[]` | transport, auth, trust boundary, pinned package |
| **Datasets** | `data` + `governance` | PII, consent basis, retention, jurisdiction, owners |
| **AI SDKs** | `library` + `purl` | `openai`, `anthropic`, `langchain`, `mcp`, … versions |
| **Providers** | `services[]` | region, DPA, data classification flowing out |
| **External AI services** | `services[]` | the ones declared once in `aibom.yaml` |

</div>

Every AI-specific fact lives under the `aibom:` property prefix, so a plain SBOM
tool ignores it and an AI-aware tool reads it.

**[The full mapping table →](docs/whats-in-the-bom.md)**

---

## 🚦 Tool & MCP risk classification

A versioned, human-readable rulebook decides each tool's **blast radius**. The
labels are `financial`, `destructive`, `code-exec`, `write`, `external-comms`,
`filesystem`, `network`, `identity`, `secrets`, `read`, `unknown`.

```console
$ aibom explain-risk issue_refund
tool 'issue_refund'
-------------------
money.movement (identifier: 'issue refund') — Moving money is irreversible and
directly monetisable by an attacker.
-> capabilities: financial
-> risk: high
```

Every verdict is a regex an auditor can read. Disagree? Override it — and the
BOM records **both** the heuristic and your decision:

```yaml
tools:
  issue_refund:
    risk: high
    human_in_the_loop: true
    reversible: false
    justification: Money movement; requires an approver and is capped per day.
```

> `aibom:risk` = yours · `aibom:heuristic_risk` = the rulebook's ·
> `aibom:risk_override=true` + justification = an auditor sees the human call.

**40+ curated MCP packages** classify servers the name alone can't reveal
(`server-github` → write + identity).

**[Generated rulebook reference →](docs/risk-rules.md)**

---

## 🔔 Review notes that catch real problems

`aibom` doesn't just inventory — it flags the things a reviewer should look at,
each with a test:

| Severity | Note | Catches |
| :---: | :--- | :--- |
| ✗ | `tool.high_risk_no_hitl` | a high-risk tool with no human in the loop |
| ✗ | `model.retired` | a model that has been retired by its provider |
| ! | `model.floating` | an alias that can change under you |
| ! | `mcp.http` | an MCP server over plain HTTP |
| ! | `mcp.unpinned_package` | an MCP package with no version pin |
| ! | `provider.no_dpa` | an AI provider with no data-processing agreement |
| ! | `prompt.no_owner` | a prompt no one is accountable for |
| ! | `dataset.pii_no_consent` | PII with no consent basis or retention |
| · | `model.no_evals` | a model with no evaluation reference |

`aibom generate --strict` exits non-zero on any ✗ — wire it into CI and the
question "did we ship a risky AI change?" answers itself.

---

## 🔀 Diff between releases

```console
$ aibom diff aibom-1.3.cdx.json aibom-1.4.cdx.json --format markdown
```

```markdown
## AI BOM changes

**3 added · 1 removed · 2 changed** (`ae7cb2e4` → `2cf89618`)

### Model
| Changed | |
| --- | --- |
| `gpt-4.1` | floating `false` → `true` |

### Tool
| Added | |
| --- | --- |
| `delete_customer_account` | new · risk **high** |
```

Gate a PR on it:

```bash
aibom diff old.json new.json --fail-on risk-increase    # any tool got riskier
aibom diff old.json new.json --fail-on new-high-risk    # a new high-risk tool
aibom diff old.json new.json --fail-on new-provider     # new AI vendor
```

---

## ✍️ Sign it

```console
$ aibom attest aibom.cdx.json
✓ signed aibom.cdx.json (cosign, keyless)
  digest: 2cf89618a345d1a464292cada8a680ddbc6550d5f1a8d4e8a131fa2198fd524f
  bundle: aibom.cdx.json.sigstore.json

$ aibom verify aibom.cdx.json --identity "$GITHUB_WORKFLOW_REF"
✓ digest matches · ✓ signature valid for the expected identity
```

> 🔒 **`generate` never touches the network.** No telemetry. The only command
> that leaves the machine is `attest`, which publishes the BOM's *digest* to the
> public sigstore transparency log — and only when you run it on purpose.

**[Signing & verification →](docs/signing.md)**

---

## 🤖 Integrate

**GitHub Action**

```yaml
- uses: modelsurface/aibom/.github/actions/aibom@v0.1.0
  with:
    strict: "true"   # fail on high-risk tools without human oversight
```

Generate → validate → render → optional sign → upload artifact → **sticky PR
comment with the AI-BOM diff**. Attach to every release with one more line.

**[Release integration →](docs/release-integration.md)**

**Python API**

```python
from aibom import generate, diff, render_markdown, validate_bom

bom = generate(".")                    # the same code path as the CLI
validate_bom(bom)
print(render_markdown(bom))
changes = diff("old.cdx.json", "new.cdx.json")
```

**Security pipelines** — Dependency-Track, GUAC, any CycloneDX ingestor:

```bash
curl -X POST "$DTRACK/api/v1/bom" -H "X-Api-Key: $KEY" \
  -F autoCreate=true -F projectName=support-agent \
  -F projectVersion=1.4.0 -F bom=@aibom.cdx.json
```

`--merge-sbom sbom.cdx.json` folds your software SBOM in, so **one upload carries
both layers**.

---

## 🧩 Compared to what you have

| | SBOM tools | Spreadsheet | **aibom** |
| :--- | :---: | :---: | :---: |
| Software dependencies | ✅ | — | ✅ (`--merge-sbom`) |
| Models & model cards | — | partial | ✅ |
| Prompts with owners | — | — | ✅ |
| Tools with blast-radius | — | — | ✅ |
| MCP servers & trust boundary | — | — | ✅ |
| Datasets, PII, consent basis | — | partial | ✅ |
| Diffable between releases | ✅ | — | ✅ |
| Signed (sigstore) | ✅ | — | ✅ |
| Human-readable report | partial | ✅ | ✅ |
| Stays current by itself | ✅ | ❌ | ✅ (CI) |

---

## 🛡️ Evidence, not compliance

`aibom` produces inventory and evidence. It does **not** decide whether your
system is lawful and makes **no** claim that a document makes you "EU AI Act
compliant". It gives auditors and governance boards the facts they ask for, in a
format their tools already accept.

**[Neutral BOM-field → EU AI Act / ISO 42001 / NIST AI RMF table →](docs/framework-mapping.md)**

---

## 📚 Documentation

| | |
| :--- | :--- |
| [Quickstart](docs/quickstart.md) | zero to a signed BOM in five minutes |
| [What's in the BOM](docs/whats-in-the-bom.md) | the full mapping table |
| [`aibom.yaml` reference](docs/manifest.md) | every field, with examples |
| [Risk rules](docs/risk-rules.md) | generated from the rulebook YAML |
| [Inputs](docs/inputs.md) | lock, CODEOWNERS, git, SDK lockfiles, merge |
| [Release integration](docs/release-integration.md) | Action, releases, Dependency-Track |
| [Signing](docs/signing.md) | attest/verify, keyless sigstore |
| [Framework mapping](docs/framework-mapping.md) | evidence, not compliance |
| [FAQ](docs/faq.md) | the questions that come up every time |

---

## 🗺️ Roadmap

- [x] CycloneDX 1.6 JSON + XML, ML-BOM component types
- [x] Stable content digest, `--previous` version increment
- [x] Transparent capability rulebook + 40 curated MCP packages
- [x] Markdown / HTML / PDF reports with a Mermaid dependency graph
- [x] `diff` with `--fail-on` gates
- [x] Keyless sigstore `attest` / `verify`
- [ ] SPDX 3.0 AI & Dataset profile export
- [ ] AI advisories — model retirements as vulnerabilities feeding Dependency-Track
- [ ] Policy-as-code (`aibom policy`) with OPA/Rego
- [ ] Org-level roll-up (`aibom merge` across repos)
- [ ] Backstage plugin

**[Changelog →](CHANGELOG.md)**

---

## 🤝 Contributing

The most valuable contributions are **data**: new MCP package classifications,
new capability rules, and framework-mapping rows. Each is a small, reviewable
YAML or Markdown diff — and the docs are generated from the data, so they can
never drift.

```bash
make dev     # editable install + pre-commit
make check   # lint + type + docs-check + test
```

See **[CONTRIBUTING.md](CONTRIBUTING.md)** and
**[examples/gallery/](examples/gallery/)** for anonymised example BOMs.

---

<div align="center">

**Standards first.** CycloneDX 1.6 · ML-BOM · sigstore
**Everything inferable is inferred; everything else is declared once.**

Apache-2.0 · built by [modelsurface](https://github.com/modelsurface)

<sub>If `aibom` caught something in your repo you didn't know was there, ⭐ the repo and tell us about it.</sub>

</div>

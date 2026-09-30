# `aibom.yaml` reference

Everything inferable is inferred. The manifest is for the facts that only a
human knows: what the system is for, who owns it, which third-party AI services
it calls that never appear in code, and where you disagree with the risk
heuristic.

`aibom init` writes a commented example. `aibom manifest validate` checks it and
reports errors with line numbers.

```yaml
schema: 1

system:
  name: support-agent
  version: 1.4.0              # or "git" to use the tag/commit
  description: Customer support assistant that drafts and sends replies.
  owner: platform-ai@example.com
  contacts:
    - {name: Ada Lovelace, email: ada@example.com, role: accountable}
  purpose: Draft replies to inbound support tickets and summarise threads.
  deployment: customer-facing        # internal | customer-facing | embedded
  risk_classification:
    framework: "EU AI Act"           # any framework; free text is fine
    label: limited
    rationale: Interacts with end users; no safety component, no biometrics.
  human_oversight: Agents approve every outbound reply before sending.
  data_classification: customer-pii
  jurisdictions: [US, EU]
  complete:                          # the honest "did you look everywhere?"
    datasets: true
    external_services: true

models:
  gpt-4.1:
    purpose: Drafting replies and summarising ticket threads.
    hosting_region: us
    data_processing_agreement: true
    training_data_optout: true
    license: proprietary
    evals:
      - {name: Support Reply Quality, url: "https://…", score: 0.91}

tools:
  issue_refund:
    risk: high
    human_in_the_loop: true
    reversible: false
    rate_limited: true
    justification: Money movement; requires an approver and is capped per day.

mcp_servers:
  crm:
    risk: medium
    justification: Read-only token scoped to the support account.

datasets:
  - name: ticket-history
    version: rolling
    classification: confidential
    sensitive_data: [email, name]
    pii: true
    consent_basis: contract
    retention: 24 months
    jurisdiction: US
    owners: [support-platform]
    source: "https://…"

external_services:
  - name: Eleven Labs TTS
    provider: elevenlabs
    purpose: voice
    data_shared: [transcripts]
    dpa: true
```

## Field notes

### `system.version`
Set to `git` to use the tag at HEAD, or the commit when HEAD is untagged.

### `system.complete`
For every kind you declare (`datasets`, `external_services`, …), set
`complete: <kind>: true` once you are confident the declaration is exhaustive.
`aibom` then reports that kind as `complete` in `compositions[]`; otherwise it
stays `unknown`. Under-claiming completeness is safe; over-claiming is what an
auditor will find.

### `models.<alias>`
The key is the model alias as it appears in code (`gpt-4.1`). `aibom` matches it
case-insensitively and tolerates `provider/alias` forms.

### `tools.<name>` overrides
An override records *both* verdicts in the BOM: `aibom:risk` becomes your value,
`aibom:heuristic_risk` keeps the rulebook's, and `aibom:risk_override: true`
plus `aibom:risk_justification` record that a human decided. Review notes warn
when an override has no `justification`.

### `datasets[]`
Declared datasets are the only place `aibom` learns about PII. If `pii: true`
and `consent_basis` or `retention` is missing, you get a review note — that is
the point.

### Validation errors
Errors carry the line number of the offending key:

```
aibom.yaml does not match the aibom manifest schema
  line 6: models/gpt-4.1/hosting_region: 42 is not of type 'string'
hint: run `aibom manifest validate` for the same report, or see docs/manifest.md
```

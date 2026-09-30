# aibom documentation

`aibom` turns a repository into an **audit-ready AI Bill of Materials** — the
models, prompts, tools, MCP servers, datasets and providers an AI system
actually uses — as a signed, diffable CycloneDX 1.6 document, in one command.

> **Evidence, not compliance.** `aibom` produces inventory and evidence. It does
> not decide whether your system is lawful, and it makes no claim that any
> document makes you "EU AI Act compliant". See
> [framework-mapping.md](framework-mapping.md).

## Start here

| Page | What you get |
| --- | --- |
| [quickstart.md](quickstart.md) | Zero to a signed BOM in five minutes. |
| [whats-in-the-bom.md](whats-in-the-bom.md) | The full source → CycloneDX mapping table. |
| [manifest.md](manifest.md) | Every field of `aibom.yaml`, with examples. |
| [risk-rules.md](risk-rules.md) | The capability rulebook (generated from the YAML). |
| [release-integration.md](release-integration.md) | GitHub Action, release attach, Dependency-Track/GUAC. |
| [signing.md](signing.md) | `attest` / `verify`, keyless sigstore, what leaves the machine. |
| [framework-mapping.md](framework-mapping.md) | Neutral BOM-field → EU AI Act / ISO 42001 / NIST AI RMF table. |
| [faq.md](faq.md) | The questions that come up every time. |

## The one-sentence promise

> Generate a CycloneDX AI Bill of Materials from your repo, so the answer to
> "what does this AI system actually use?" is always current, diffable, and
> signed.

## Command map

```
aibom generate [path]      # produce aibom.cdx.json (+ .sha256, Markdown, HTML)
aibom init [path]          # write an example aibom.yaml
aibom validate <bom>       # re-validate against CycloneDX 1.6 + the digest
aibom render <bom>         # regenerate Markdown/HTML/PDF from the JSON
aibom diff <old> <new>     # what changed in the AI surface
aibom explain-risk <tool>  # which rule matched, and why
aibom attest <bom>         # keyless sigstore signature
aibom verify <bom>         # verify a signature (digest fallback)
aibom manifest validate    # validate aibom.yaml with line numbers
aibom doctor               # environment and input diagnostics
```

## Design rules

1. **Standards first.** CycloneDX 1.6, ML-BOM component types, sigstore.
2. **Infer everything inferable; declare the rest once** in `aibom.yaml`.
3. **Transparent rules.** An auditor can read exactly why a tool is "high risk".
4. **A stable content digest** anchors diffs, validation and attestation.
5. **Beautiful for humans, strict for machines.**
6. **No network calls** except the sigstore transparency log when you explicitly
   run `attest`. No telemetry, ever.

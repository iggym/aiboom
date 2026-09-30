# Quickstart

## Install

```bash
pip install aibom            # core: JSON + Markdown + HTML
pip install "aibom[pdf]"     # + PDF via WeasyPrint
pip install "aibom[sign]"    # + sigstore-python for keyless signing
pip install "aibom[all]"     # everything
```

Requires Python ≥ 3.11.

## 1. Generate a BOM

From the root of your repository:

```bash
aibom generate .
```

```
aibom 0.1.0 — audit-ready AI Bill of Materials (CycloneDX 1.6, rules 2026.09.1)
  · root /repo/support-agent
  · input: read surface.lock
  · manifest: /repo/support-agent/aibom.yaml
  · git: main @ e26f46b (clean)
  · inventory: 3 model(s) · 2 prompt(s) · 4 tool(s) · 2 MCP server(s) · 1 provider(s) · 2 dataset(s) · 1 external service(s) · 5 AI SDK(s)
✓ wrote /repo/support-agent/aibom.cdx.json
✓ wrote /repo/support-agent/aibom.cdx.json.sha256

review notes: 2 error(s), 3 warning(s), 2 info
  ✗ [tool.high_risk_no_hitl] High-risk tool `delete_customer_account` has no human in the loop.
  ! [mcp.unpinned_package] MCP server `@modelcontextprotocol/server-filesystem` uses an unpinned package.
  …

digest: 2cf89618a345d1a464292cada8a680ddbc6550d5f1a8d4e8a131fa2198fd524f
```

Two files land in the working directory: `aibom.cdx.json` (the machine-readable
BOM) and `aibom.cdx.json.sha256` (its stable content digest). The digest ignores
`serialNumber`, `metadata.timestamp` and `version`, so two runs over unchanged
code produce the same digest — that is what makes `diff` and attestation cheap.

## 2. Add the human-readable report

```bash
aibom generate . --markdown AIBOM.md --html AIBOM.html
```

`AIBOM.md` is what you paste into a procurement questionnaire or attach to a
release. `AIBOM.html` is a single, print-optimised file with a table of
contents. Add `--pdf AIBOM.pdf` if you installed `aibom[pdf]`.

## 3. Declare what only a human knows

Anything not visible in code — a third-party AI service, a model's purpose, a
tool's risk override — is declared once in `aibom.yaml`:

```bash
aibom init .
$EDITOR aibom.yaml
aibom manifest validate aibom.yaml
```

See [manifest.md](manifest.md) for every field.

## 4. Validate and diff

```bash
aibom validate aibom.cdx.json --strict     # schema + digest + ingestor checks
aibom diff aibom-1.3.cdx.json aibom-1.4.cdx.json --format markdown
```

`--strict` fails when review notes contain error-level findings, which is what
you want in CI. `diff --fail-on risk-increase` fails a PR that raises the risk
of any tool.

## 5. Sign (optional)

```bash
aibom attest aibom.cdx.json     # keyless sigstore via cosign
aibom verify aibom.cdx.json     # verify with digest fallback
```

Signing publishes the BOM's digest to the public sigstore transparency log. It
is never automatic — see [signing.md](signing.md).

## 6. Wire it into CI

```yaml
- uses: modelsurface/aibom/.github/actions/aibom@v0.1.0
  with:
    strict: "true"
```

Or copy [the release workflow](../.github/workflows/aibom.yml) to attach the BOM
to every release and post an AI-BOM diff on each PR.

## Using the Python API

```python
from aibom import generate, diff, render_markdown, validate_bom

bom = generate(".")                 # dict, ready for json.dump
validate_bom(bom)
changes = diff("old.cdx.json", "new.cdx.json")
print(render_markdown(bom))
```

`aibom.generate` is the same code path the CLI uses, so the API can never
produce a different BOM than `aibom generate`.

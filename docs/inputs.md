# Inputs

`aibom` reads whatever it can find and never fails because an input is missing.
Each input below is optional; when one is present the console line tells you
which path was used.

## `surface.lock` (primary)

The scanner's lockfile is the primary input. When it exists, `aibom` reads it
via `surfacelock.read_lock` and reports `input: read surface.lock`. When it is
absent — or when you pass `--refresh` — `aibom` runs the scanner in-process
(`input: scanned in-process`) and writes a fresh `surface.lock`.

Why ship a fallback scanner? So `aibom` works air-gapped and dependency-minimal.
The lock is the canonical artifact; the bundled scan exists so the tool is never
unusable.

## `aibom.yaml` (manifest)

What code cannot reveal: system purpose, owners, model cards, risk overrides,
datasets, and third-party AI services. Validated against a JSON schema with
line-numbered errors. See [manifest.md](manifest.md).

## `CODEOWNERS`

`aibom` reads `CODEOWNERS` from the repository root, `.github/`, and `docs/`,
using GitHub's matching semantics (last match wins). Owners are attached to the
prompts and tool files they cover, so the report answers "who is accountable for
this prompt?".

## Git metadata

Commit, branch, remote, tag (when HEAD is tagged) and a dirty flag go into the
provenance footer and `metadata.component`. If the directory is not a git repo,
the fields are simply omitted — `aibom` never fails on this.

## AI SDK lockfiles

`aibom` reads `requirements*.txt`, `poetry.lock`, `uv.lock`,
`package-lock.json` and `pnpm-lock.yaml` and records the versions of AI SDKs it
finds — `openai`, `anthropic`, `google-genai`, `langchain*`, `llama-index*`,
`mcp`, `@modelcontextprotocol/*`, `ai` (Vercel) and `litellm` — as `library`
components with `aibom:role=ai-sdk` and a proper `purl`.

This is the field security teams care about: "which version of the OpenAI SDK is
in production, and did it change between releases?"

## `--merge-sbom`

Pass an existing CycloneDX SBOM and `aibom` merges it, so one document carries
both the software and AI components under a single `metadata.component`. Upload
once to Dependency-Track and both layers land.

# Release integration

## GitHub Action

The composite action installs `aibom`, generates the BOM, validates it, signs it
(optional), uploads artifacts and comments a diff on the PR.

```yaml
name: aibom
on: [push, pull_request]
permissions:
  contents: read
  pull-requests: write
  id-token: write        # only for signing

jobs:
  aibom:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: modelsurface/aibom/.github/actions/aibom@v0.1.0
        with:
          strict: "true"       # fail on error-level review notes
          sign: "false"        # set true to publish the digest to sigstore
```

### Inputs

| Input | Default | Meaning |
| --- | --- | --- |
| `path` | `.` | repository path to scan |
| `output` | `aibom.cdx.json` | CycloneDX JSON output |
| `markdown` | `AIBOM.md` | Markdown report (`""` to skip) |
| `html` | `""` | HTML report (`""` to skip) |
| `strict` | `false` | fail on error-level review notes |
| `refresh` | `true` | force a fresh scan |
| `sign` | `false` | keyless sigstore signing |
| `comment` | `true` | sticky PR comment with the AI-BOM diff |
| `upload-artifact` | `true` | upload BOM + reports |
| `python-version` | `3.12` | Python for the runner |

### Outputs

| Output | Meaning |
| --- | --- |
| `bom-path` | path to the generated JSON BOM |
| `digest` | the stable content digest |

### Attach to a release

See [`.github/workflows/aibom.yml`](../.github/workflows/aibom.yml). The key
steps:

```yaml
- run: aibom generate . -o aibom.cdx.json --markdown AIBOM.md --refresh
- run: aibom validate aibom.cdx.json --strict
- run: aibom attest aibom.cdx.json            # optional
- run: gh release upload "$TAG" aibom.cdx.json aibom.cdx.json.sha256 AIBOM.md
```

### PR diff comment

The workflow generates the BOM for the base branch, diffs it against the PR's,
and posts one sticky comment (`<!-- aibom-diff -->`) that it updates in place.
Reviewers see exactly which models, tools, prompts, providers and MCP servers
changed — and the review notes the change introduced.

## pre-commit hook

Keep `aibom.cdx.json` fresh on every commit that touches the AI surface:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: aibom-generate
        name: aibom generate
        entry: aibom-generate
        language: python
        additional_dependencies: ["aibom"]
        pass_filenames: false
        always_run: true
```

**Trade-offs, stated plainly.** The hook rewrites a committed artifact, so a
commit that touches the AI surface will include an `aibom.cdx.json` diff. That
noise is the feature: a stale BOM in `main` is the worse outcome. It also needs
`aibom` installed in the hook environment, costing a few seconds on the first run
of each session. The hook runs with `--strict`, so a high-risk tool without human
oversight cannot be committed silently.

If you prefer the BOM to be a build artifact rather than a committed file, skip
the hook and use the Action — both are supported.

## Dependency-Track

Security teams already ingest SBOMs; the point of CycloneDX output is that the AI
layer rides the same pipeline.

```bash
curl -X POST "https://dtrack.example.com/api/v1/bom" \
  -H "X-Api-Key: $DTRACK_API_KEY" \
  -F "autoCreate=true" \
  -F "projectName=support-agent" \
  -F "projectVersion=1.4.0" \
  -F "bom=@aibom.cdx.json"
```

`aibom generate --merge-sbom sbom.cdx.json` merges an existing software SBOM into
the output, so one upload carries both the software and the AI components under a
single `metadata.component`. The Python helper is available too:

```python
from aibom.integrations.dependency_track import upload
upload("aibom.cdx.json", url="https://dtrack.example.com",
       api_key=..., project_name="support-agent", project_version="1.4.0")
```

A nightly job (`.github/workflows/nightly-dtrack.yml`) spins up a real
Dependency-Track container and proves the BOM is accepted — that is the check
that turns "valid CycloneDX" into "ingestible by the tools you already run".

## GUAC

GUAC ingests CycloneDX directly:

```bash
guaccollect files --path aibom.cdx.json
```

Because `aibom` keys everything on `bom-ref` and emits a `dependencies[]` graph
from the application, the AI components show up attached to the project rather
than as orphans.

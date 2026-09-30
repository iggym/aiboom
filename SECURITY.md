# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately via GitHub's
[security advisories](https://github.com/modelsurface/aibom/security/advisories/new)
rather than a public issue. We aim to acknowledge within three working days.

## What aibom does with your data

- `generate`, `validate`, `render`, `diff`, `explain-risk`, `manifest validate`
  and `doctor` make **no network calls**. There is no telemetry and no
  phone-home.
- The only command that leaves the machine is **`attest`**, which publishes the
  BOM's digest to the sigstore transparency log. It never uploads the BOM
  contents, and it only runs when you invoke it.
- The BOM can contain sensitive inventory (internal hostnames, model aliases,
  dataset names). Treat `aibom.cdx.json` and `AIBOM.md` as you would any other
  internal document, and review them before attaching to a public release.

## Supply chain

- Core runtime dependencies are `pyyaml` and `jsonschema`.
- `surfacelock`, `weasyprint`, `sigstore` and `lxml` are optional extras.
- Releases are published to PyPI via trusted publishing (no long-lived token)
  and signed with sigstore; the release workflow is in
  `.github/workflows/release.yml`.

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | ✅ |

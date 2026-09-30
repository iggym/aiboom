# Signing & verification

`aibom` signs BOMs with **keyless sigstore**, the same trust model used for
container images and software artifacts. There is no key to manage: the signature
is bound to an OIDC identity (a GitHub Actions workflow, a Google account, …) and
recorded in the public transparency log.

## The one rule

> **Signing publishes the BOM's digest to a public transparency log. Nothing
> else is sent anywhere. `aibom generate` never touches the network.**

`aibom` makes no network calls except during `attest`. There is no telemetry, no
phone-home, no update check.

## Sign

```bash
pip install "aibom[sign]"          # or: install cosign
aibom attest aibom.cdx.json
```

```
✓ signed aibom.cdx.json (cosign, keyless)
  digest: 2cf89618a345d1a464292cada8a680ddbc6550d5f1a8d4e8a131fa2198fd524f
  bundle: aibom.cdx.json.sigstore.json
  verify: aibom verify aibom.cdx.json --identity <you> --issuer <issuer>
```

Two backends are tried, in order:

1. **`cosign sign-blob --bundle`** if `cosign` is on `PATH`.
2. **`sigstore-python`** if the `[sign]` extra is installed.

The output is a `.sigstore.json` bundle next to the BOM. In CI you need
`id-token: write` in the workflow permissions.

## Verify

```bash
aibom verify aibom.cdx.json
aibom verify aibom.cdx.json --identity https://github.com/you/repo/.github/workflows/release.yml@refs/tags/v1.0.0 \
                            --issuer https://token.actions.githubusercontent.com
```

Verification has two layers:

1. **Digest check.** The BOM is re-hashed and compared to the `.sha256` sidecar.
   This always runs and catches a tampered file.
2. **Signature check.** The sigstore bundle is verified against the expected
   identity and issuer. If no bundle is present, `verify` reports that clearly
   and falls back to the digest result — it does not silently pass.

Exit code `6` means "digest fine, no signature". Pass `--require-signature` to
make that a failure.

## GitHub Actions

```yaml
permissions:
  id-token: write      # required for keyless signing
  contents: write      # only if you attach to a release

- run: aibom attest aibom.cdx.json
- run: aibom verify aibom.cdx.json --identity "${{ github.workflow_ref }}" \
                                   --issuer https://token.actions.githubusercontent.com
```

You can also use GitHub-native attestations instead:

```bash
gh attestation create aibom.cdx.json --predicate-type https://cyclonedx.org/bom
gh attestation verify aibom.cdx.json --repo you/repo
```

`aibom attest` prints this guidance so the choice is visible.

## What a verifier proves

A verified bundle proves three things and no more:

- the file has not changed since it was signed (the digest),
- **who** signed it (the OIDC identity),
- **when**, and that the signature is in the transparency log.

It does not prove the BOM is *correct* — only that the BOM you are reading is the
one that was produced by that identity at that time. That is the property an
auditor actually needs.

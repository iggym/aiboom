# Contributing to aibom

Thanks for helping. The most valuable contributions are **data**: rules, MCP
package classifications, and framework-mapping rows. Each is a small, reviewable
YAML or Markdown diff, and the docs are generated from the data so they cannot
drift.

## The compounding assets

| Asset | File | What to add |
| --- | --- | --- |
| Capability rules | `src/aibom/risk/rules/capabilities.yaml` | A regex over the tool haystack, with a `why` an auditor can read |
| Curated MCP packages | `src/aibom/risk/rules/mcp-packages.yaml` | A package name, its capabilities, and a `why` |
| Framework mapping | `docs/framework-mapping.md` | A row whose BOM field *actually* carries the fact the framework asks for |

### Adding a capability rule

```yaml
  - id: domain.money-laundering
    capability: financial
    why: Moving value cross-border is monetisable and hard to reverse.
    identifier: '\b(remit|wire|swift|iban|sepa)\b'
```

Every rule needs an `id`, a `capability` (one of the labels in
`capability_levels`), a `why`, and at least one field pattern. If one field only
qualifies another, add `match: all` and document which is the object and which
the verb.

After editing, regenerate the docs and run the tests:

```bash
make docs        # or: python -m aibom.risk.docs
make check       # lint + type + docs-check + test
```

`make docs-check` fails if `docs/risk-rules.md` is stale, so the docs and the
rulebook can never disagree.

### Adding a curated MCP package

```yaml
  - package: "@modelcontextprotocol/server-stripe"
    capabilities: [financial]
    why: Payment APIs can move money; treat as a financial surface.
```

Curated entries act as a *floor* on classification: they add capabilities the
package name alone cannot reveal. The classifier still runs the rules on top.

## Code contributions

1. Read the relevant spec section and the tests that cover it.
2. Prefer a failing test first — the test suite is organised by feature
   (`test_risk_rules.py`, `test_diff.py`, `test_golden_boms.py`, …).
3. Keep the public API surface small. Most logic belongs in a module the API
   calls, so the CLI and the Python API can never diverge.
4. Run `make check` before opening a PR.

## Tests

```bash
make test                  # the default suite, minus external services
pytest -m slow             # needs a Dependency-Track container
pytest -m cosign           # needs a local cosign binary
```

Golden BOMs live in `tests/fixtures/golden/`. If a mapping change is intentional,
regenerate with `AIBOM_UPDATE_GOLDEN=1 pytest tests/test_golden_boms.py` and
review the diff like any other code change.

## Style

- Typed, mypy-clean, `ruff`-clean (`make lint type`).
- Comments explain *why*, not *what*. A rule's `why` is part of the product;
  keep it plain and specific.

## Security

`aibom` makes no network calls outside `attest`. Do not add telemetry, and do not
add a network call that runs on `generate`. If a change needs the network, it
belongs behind an explicit command the user runs on purpose.

## License

By contributing you agree your contributions are licensed under Apache-2.0.

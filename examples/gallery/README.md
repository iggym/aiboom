# Example gallery

Anonymised AI BOMs contributed by users, so you can see the shape of the output
before you generate your own. Each entry is a real (or realistic) repo reduced
to the interesting parts.

## Contribute yours

```bash
aibom generate . -o my-system.cdx.json --markdown my-system.md --refresh
# anonymise names, hosts and secrets, then open a PR adding a folder here:
#   examples/gallery/<your-system>/
#     README.md          — one paragraph: what the system is, what aibom caught
#     aibom.yaml         — the manifest (redacted)
#     aibom.cdx.json     — the BOM
#     AIBOM.md           — the rendered report
```

The rule for accepting an entry: it must show something the inventory caught
that a human would otherwise have missed. A BOM that just lists `openai` is not
interesting; a BOM that surfaces a high-risk tool without human oversight, or an
MCP server over plain HTTP, is.

## Entries

| System | Shape | What it shows |
| --- | --- | --- |
| [support-agent](support-agent/) | Customer-facing agent with a payments tool | Review notes catching a high-risk tool with no human in the loop and an unpinned MCP package |
| [rag-service](rag-service/) | Internal retrieval service | Dataset governance fields and `compositions` completeness |
| [mcp-heavy](mcp-heavy/) | Research agent wired to many MCP servers | Curated MCP package classification and blast-radius ranking |

These three mirror the fixtures in `tests/fixtures/`, which are also the golden
BOMs in the test suite — so the examples and the tests describe the same repos.

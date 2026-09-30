"""`aibom` command line interface (spec §6.6).

Commands: generate · init · validate · render · diff · explain-risk · attest ·
verify · manifest validate · doctor.

Exit codes are the contract used by CI and the GitHub Action:

    0  ok
    1  general error
    2  usage error
    3  validation failed (schema, manifest, lock)
    4  review notes present with --strict
    5  a diff gate tripped
    6  signature/digest verification failed
    7  an optional extra is missing
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aibom import RULES_VERSION, __version__
from aibom.errors import (
    EXIT_GENERAL_ERROR,
    EXIT_OK,
    EXIT_VERIFY_FAILED,
    AibomError,
    StrictReviewError,
    UsageError,
    as_json_error,
)

PROG = "aibom"

BANNER = f"{PROG} {__version__} — audit-ready AI Bill of Materials (CycloneDX 1.6, rules {RULES_VERSION})"


# --- output helpers -----------------------------------------------------------


class Console:
    """Minimal console with colour only when it is safe to use."""

    def __init__(self, *, colour: bool | None = None, quiet: bool = False) -> None:
        if colour is None:
            colour = sys.stderr.isatty() and not quiet
        self.colour = colour
        self.quiet = quiet

    def _wrap(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.colour else text

    def info(self, message: str) -> None:
        if not self.quiet:
            print(message)

    def step(self, message: str) -> None:
        if not self.quiet:
            print(f"  {self._wrap('·', '36')} {message}")

    def ok(self, message: str) -> None:
        if not self.quiet:
            print(f"{self._wrap('✓', '32')} {message}")

    def warn(self, message: str) -> None:
        print(f"{self._wrap('!', '33')} {message}", file=sys.stderr)

    def error(self, message: str) -> None:
        print(f"{self._wrap('✗', '31')} {message}", file=sys.stderr)


# --- parser -------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=BANNER,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  aibom init\n"
            "  aibom generate --markdown AIBOM.md --html AIBOM.html\n"
            "  aibom generate --format xml -o aibom.cdx.xml\n"
            "  aibom diff aibom-v1.cdx.json aibom.cdx.json --format markdown\n"
            "  aibom explain-risk issue_refund\n"
            "  aibom attest aibom.cdx.json && aibom verify aibom.cdx.json\n"
        ),
    )
    parser.add_argument("--version", action="version", version=BANNER)
    parser.add_argument("--no-color", action="store_true", help="disable coloured output")
    parser.add_argument("--quiet", action="store_true", help="suppress progress output")
    parser.add_argument("--json", action="store_true", help="machine-readable output where supported")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # generate -----------------------------------------------------------------
    gen = sub.add_parser("generate", help="generate the AI BOM")
    gen.add_argument("path", nargs="?", default=".", help="repository root (default: .)")
    gen.add_argument("-o", "--output", default="aibom.cdx.json", help="BOM output path")
    gen.add_argument("--format", choices=["json", "xml"], default="json")
    gen.add_argument("--markdown", metavar="FILE", help="also write Markdown")
    gen.add_argument("--html", metavar="FILE", help="also write single-file HTML")
    gen.add_argument("--pdf", metavar="FILE", help="also write PDF (needs the [pdf] extra)")
    gen.add_argument("--refresh", action="store_true", help="ignore surface.lock and rescan")
    gen.add_argument("--manifest", metavar="FILE", help="explicit aibom.yaml")
    gen.add_argument("--lock", metavar="FILE", help="explicit surface.lock")
    gen.add_argument("--scanner", choices=["auto", "surfacelock", "bundled"], default="auto")
    gen.add_argument("--previous", metavar="FILE", help="previous BOM; increments `version`")
    gen.add_argument("--merge-sbom", metavar="FILE", help="merge an existing CycloneDX SBOM")
    gen.add_argument(
        "--strict",
        action="store_true",
        help="exit 4 when review notes contain any error",
    )
    gen.add_argument("--no-validate", action="store_true", help="skip schema validation (not advised)")
    gen.add_argument(
        "--print-digest",
        action="store_true",
        help="print only the content digest (for CI variables)",
    )

    # init ---------------------------------------------------------------------
    init = sub.add_parser("init", help="write an example aibom.yaml")
    init.add_argument("path", nargs="?", default=".")
    init.add_argument("--force", action="store_true", help="overwrite an existing manifest")

    # validate -----------------------------------------------------------------
    val = sub.add_parser("validate", help="validate a BOM against the CycloneDX schema")
    val.add_argument("bom")
    val.add_argument("--strict", action="store_true", help="also run ingestion checks")
    val.add_argument("--digest", action="store_true", help="also verify the .sha256 sidecar")

    # render -------------------------------------------------------------------
    ren = sub.add_parser("render", help="render Markdown/HTML/PDF from a BOM")
    ren.add_argument("bom")
    ren.add_argument("--markdown", metavar="FILE")
    ren.add_argument("--html", metavar="FILE")
    ren.add_argument("--pdf", metavar="FILE")
    ren.add_argument("-o", "--output", help="shortcut for --markdown FILE")

    # diff ---------------------------------------------------------------------
    dif = sub.add_parser("diff", help="diff two BOMs")
    dif.add_argument("old")
    dif.add_argument("new")
    dif.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    dif.add_argument("--fail-on-change", action="store_true", help="exit 5 on any change")
    dif.add_argument(
        "--fail-on",
        action="append",
        default=[],
        metavar="GATE",
        help="risk-increase | new-high-risk | new-provider | any-change (repeatable)",
    )
    dif.add_argument("-o", "--output", metavar="FILE", help="write the diff to a file")

    # explain-risk -------------------------------------------------------------
    exp = sub.add_parser("explain-risk", help="explain why a tool/MCP server got its risk")
    exp.add_argument("name")
    exp.add_argument("--kind", choices=["tool", "mcp"], default="tool")
    exp.add_argument("--json", action="store_true")

    # attest / verify ----------------------------------------------------------
    att = sub.add_parser("attest", help="keyless-sign a BOM with sigstore")
    att.add_argument("bom")
    att.add_argument("--predicate-type", default="https://cyclonedx.org/bom")
    att.add_argument("--identity-token", help="explicit OIDC token (CI)")
    att.add_argument("--offline", action="store_true", help="use ambient credentials only")

    ver = sub.add_parser("verify", help="verify a BOM's signature and digest")
    ver.add_argument("bom")
    ver.add_argument("--identity", help="expected certificate identity (email or workflow)")
    ver.add_argument("--issuer", help="expected OIDC issuer")
    ver.add_argument("--require-signature", action="store_true")

    # manifest -----------------------------------------------------------------
    man = sub.add_parser("manifest", help="manifest operations")
    man_sub = man.add_subparsers(dest="manifest_command", metavar="<subcommand>")
    man_val = man_sub.add_parser("validate", help="validate aibom.yaml")
    man_val.add_argument("manifest", nargs="?", default=None)
    man_val.add_argument("path", nargs="?", default=".")

    # doctor -------------------------------------------------------------------
    doc = sub.add_parser("doctor", help="diagnose the environment and repository")
    doc.add_argument("path", nargs="?", default=".")

    # rules --------------------------------------------------------------------
    rul = sub.add_parser("rules", help="print the rulebook (docs generation)")
    rul.add_argument("--markdown", action="store_true", help="emit Markdown for docs/risk-rules.md")

    return parser


# --- command implementations --------------------------------------------------


def cmd_generate(args: argparse.Namespace, console: Console) -> int:
    from aibom.api import GenerateOptions, generate_full
    from aibom.digest import digest_of, write_digest
    from aibom.model.cyclonedx import json_to_xml
    from aibom.render import PRINT_INSTRUCTIONS, render_html, render_markdown, render_pdf
    from aibom.risk import has_errors, summarise

    root = Path(args.path).resolve()
    options = GenerateOptions(
        root=root,
        manifest=Path(args.manifest) if args.manifest else None,
        lock=Path(args.lock) if args.lock else None,
        refresh=args.refresh,
        scanner=args.scanner,
        previous=Path(args.previous) if args.previous else None,
        merge_sbom=Path(args.merge_sbom) if args.merge_sbom else None,
        validate=not args.no_validate,
    )
    bom, model = generate_full(options)

    console.info(BANNER)
    console.step(f"root {root}")
    console.step(
        f"input: {'scanned in-process (' + model.scanner + ')' if model.lock_generated else 'surface.lock'}"
        f" → {model.lock_path}"
    )
    console.step(f"manifest: {model.manifest_path or 'none (inference-only)'}")
    console.step(f"git: {model.git.get('commit', 'unavailable') if model.git.get('available') else 'unavailable'}")
    console.step(f"inventory: {model.summary_line()}")

    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    if args.format == "xml":
        output.write_text(json_to_xml(bom), encoding="utf-8")
    else:
        output.write_text(json.dumps(bom, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        write_digest(bom, output)
    console.ok(f"wrote {output}")

    digest = digest_of(bom)
    if args.print_digest:
        print(digest)

    if args.markdown:
        target = Path(args.markdown)
        target.write_text(render_markdown(bom), encoding="utf-8")
        console.ok(f"wrote {target}")
    if args.html:
        target = Path(args.html)
        target.write_text(render_html(bom), encoding="utf-8")
        console.ok(f"wrote {target}")
    if args.pdf:
        target = Path(args.pdf)
        try:
            render_pdf(bom, target)
        except AibomError as exc:
            console.warn(exc.render())
            console.warn(PRINT_INSTRUCTIONS)
        else:
            console.ok(f"wrote {target}")

    console.info("")
    console.info(f"review notes: {summarise(model.review_notes)}")
    for note in model.review_notes:
        mark = {"error": "✗", "warning": "!", "info": "·"}[note.level]
        console.info(f"  {mark} [{note.code}] {note.message}")
    console.info("")
    console.info(f"digest: {digest}")

    if args.json:
        print(
            json.dumps(
                {
                    "bom": str(output),
                    "digest": digest,
                    "inventory": model.counts(),
                    "review_notes": [n.as_dict() for n in model.review_notes],
                    "summary": summarise(model.review_notes),
                },
                indent=2,
            )
        )

    if args.strict and has_errors(model.review_notes):
        raise StrictReviewError(
            f"{sum(1 for n in model.review_notes if n.level == 'error')} review-note error(s) "
            "and --strict was set"
        )
    return EXIT_OK


def cmd_init(args: argparse.Namespace, console: Console) -> int:
    from aibom.manifest import write_example_manifest

    root = Path(args.path).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = write_example_manifest(root, force=args.force)
    console.ok(f"wrote {target}")
    console.info("Next: edit it, then run `aibom generate --markdown AIBOM.md`.")
    return EXIT_OK


def cmd_validate(args: argparse.Namespace, console: Console) -> int:
    from aibom.digest import verify_digest
    from aibom.validate import validate_file

    path = Path(args.bom)
    bom = validate_file(path, strict=args.strict)
    console.ok(f"{path} is valid CycloneDX {bom.get('specVersion')}")
    if args.digest:
        ok, expected, actual = verify_digest(path, bom)
        if ok:
            console.ok(f"digest matches sidecar ({actual[:12]})")
        else:
            console.warn(
                f"digest mismatch: sidecar {expected[:12] or '(absent)'} vs computed {actual[:12]}"
            )
            return EXIT_VERIFY_FAILED
    if args.json:
        print(json.dumps({"valid": True, "specVersion": bom.get("specVersion")}, indent=2))
    return EXIT_OK


def cmd_render(args: argparse.Namespace, console: Console) -> int:
    from aibom.render import render_html, render_markdown, render_pdf
    from aibom.validate import validate_file

    path = Path(args.bom)
    bom = validate_file(path)
    wrote = False
    if args.output and not args.markdown:
        args.markdown = args.output
    if args.markdown:
        Path(args.markdown).write_text(render_markdown(bom), encoding="utf-8")
        console.ok(f"wrote {args.markdown}")
        wrote = True
    if args.html:
        Path(args.html).write_text(render_html(bom), encoding="utf-8")
        console.ok(f"wrote {args.html}")
        wrote = True
    if args.pdf:
        render_pdf(bom, Path(args.pdf))
        console.ok(f"wrote {args.pdf}")
        wrote = True
    if not wrote:
        sys.stdout.write(render_markdown(bom))
    return EXIT_OK


def cmd_diff(args: argparse.Namespace, console: Console) -> int:
    from aibom.diff import (
        check_gates,
        render_diff_markdown,
        render_diff_text,
    )
    from aibom.diff import (
        diff as diff_files,
    )

    result = diff_files(Path(args.old), Path(args.new))
    if args.format == "json":
        payload = json.dumps(result.as_dict(), indent=2)
    elif args.format == "markdown":
        payload = render_diff_markdown(result)
    else:
        payload = render_diff_text(result)

    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
        console.ok(f"wrote {args.output}")
    else:
        sys.stdout.write(payload)
        if not payload.endswith("\n"):
            sys.stdout.write("\n")

    gates = list(args.fail_on)
    if args.fail_on_change:
        gates.append("any-change")
    if gates:
        check_gates(result, gates)
    return EXIT_OK


def cmd_explain_risk(args: argparse.Namespace, console: Console) -> int:
    from aibom.risk import classify_mcp_server, classify_tool

    result = classify_mcp_server(args.name) if args.kind == "mcp" else classify_tool(args.name)
    if args.json:
        print(
            json.dumps(
                {
                    "name": args.name,
                    "kind": args.kind,
                    "capabilities": result.capabilities,
                    "risk": result.risk,
                    "matches": [m.as_dict() for m in result.matches],
                    "curated": result.curated,
                },
                indent=2,
            )
        )
        return EXIT_OK
    header = f"{args.kind} {args.name!r}"
    console.info(header)
    console.info("-" * len(header))
    console.info(result.explain())
    return EXIT_OK


def cmd_attest(args: argparse.Namespace, console: Console) -> int:
    from aibom.sign import GH_ATTESTATION_GUIDANCE, attest

    result = attest(
        Path(args.bom),
        predicate_type=args.predicate_type,
        identity_token=args.identity_token,
        offline=args.offline,
    )
    console.ok(f"signed with {result.method}: {result.bundle or result.signature}")
    console.info(f"digest: {result.digest}")
    console.info("")
    console.info(GH_ATTESTATION_GUIDANCE)
    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
    return EXIT_OK


def cmd_verify(args: argparse.Namespace, console: Console) -> int:
    from aibom.sign import verify

    result = verify(
        Path(args.bom),
        identity=args.identity,
        issuer=args.issuer,
        require_signature=args.require_signature,
    )
    if result.ok:
        console.ok(result.detail)
        console.info(f"method: {result.method} · digest ok: {result.digest_ok}")
    else:
        console.error(f"verification failed: {result.detail}")
    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
    return EXIT_OK if result.ok else EXIT_VERIFY_FAILED


def cmd_manifest(args: argparse.Namespace, console: Console) -> int:
    from aibom.manifest import load_manifest, manifest_summary

    if args.manifest_command != "validate":
        raise UsageError(
            "`aibom manifest` needs a subcommand",
            hint="try `aibom manifest validate [aibom.yaml]`",
        )
    root = Path(args.path).resolve()
    explicit = Path(args.manifest).resolve() if args.manifest else None
    manifest = load_manifest(root, explicit, required=True)
    summary = manifest_summary(manifest)
    console.ok(f"{summary['path']} is valid (schema 1)")
    for key, value in summary.items():
        if key != "path":
            console.info(f"  {key}: {value}")
    if args.json:
        print(json.dumps({"valid": True, **summary}, indent=2))
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace, console: Console) -> int:
    from aibom.doctor import as_dict, exit_code, render_doctor, run_doctor

    findings = run_doctor(Path(args.path))
    console.info(render_doctor(findings, colour=console.colour))
    if args.json:
        print(json.dumps(as_dict(findings), indent=2))
    return exit_code(findings)


def cmd_rules(args: argparse.Namespace, console: Console) -> int:
    from aibom.risk import load_rulebook, rulebook_as_markdown

    if args.markdown:
        sys.stdout.write(rulebook_as_markdown())
        return EXIT_OK
    book = load_rulebook()
    console.info(f"rulebook {book.rules_version} · registry {book.registry_version}")
    console.info(f"{len(book.rules)} rules, {len(book.packages)} curated MCP packages")
    console.info("")
    for rule in book.rules:
        console.info(f"  {rule.get('id')}: {rule.get('capability')} — {rule.get('why', '')}")
    if args.json:
        print(
            json.dumps(
                {
                    "rules_version": book.rules_version,
                    "registry_version": book.registry_version,
                    "rules": book.rules,
                    "packages": book.packages,
                    "name_patterns": book.name_patterns,
                },
                indent=2,
            )
        )
    return EXIT_OK


_COMMANDS = {
    "generate": cmd_generate,
    "init": cmd_init,
    "validate": cmd_validate,
    "render": cmd_render,
    "diff": cmd_diff,
    "explain-risk": cmd_explain_risk,
    "attest": cmd_attest,
    "verify": cmd_verify,
    "manifest": cmd_manifest,
    "doctor": cmd_doctor,
    "rules": cmd_rules,
}


#: Global flags that may appear before *or* after the subcommand.
_GLOBAL_FLAGS = ("--quiet", "--no-color", "--json")


def _hoist_global_flags(argv: list[str]) -> list[str]:
    """Move global flags to the front so they parse with the top-level parser.

    `aibom generate --quiet` and `aibom --quiet generate` are both natural;
    argparse's subparsers would only accept the second, so normalise.
    """
    hoisted: list[str] = []
    rest: list[str] = []
    for token in argv:
        if token in _GLOBAL_FLAGS:
            hoisted.append(token)
        else:
            rest.append(token)
    return hoisted + rest


def main(argv: list[str] | None = None) -> int:
    argv = _hoist_global_flags(list(sys.argv[1:] if argv is None else argv))
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console(colour=False if getattr(args, "no_color", False) else None, quiet=args.quiet)

    if not args.command:
        parser.print_help()
        return EXIT_OK

    handler = _COMMANDS.get(args.command)
    if handler is None:  # pragma: no cover - argparse rejects unknown commands
        parser.error(f"unknown command {args.command!r}")
        return 2

    try:
        return handler(args, console)
    except AibomError as exc:
        if getattr(args, "json", False):
            print(json.dumps(as_json_error(exc), indent=2), file=sys.stderr)
        else:
            console.error(exc.render())
        return exc.exit_code
    except FileNotFoundError as exc:
        console.error(f"error: {exc}")
        return EXIT_GENERAL_ERROR
    except KeyboardInterrupt:  # pragma: no cover
        console.error("interrupted")
        return 130
    except Exception as exc:  # noqa: BLE001 - top-level guard, never a raw traceback
        console.error(f"error: unexpected failure: {type(exc).__name__}: {exc}")
        if not getattr(args, "quiet", False):
            console.error("run with --json for a machine-readable report, or `aibom doctor`")
        return EXIT_GENERAL_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

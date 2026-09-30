"""pre-commit hook: keep `aibom.cdx.json` fresh (spec §6.7).

Trade-offs, stated plainly because they are the reason this is optional:

* The hook rewrites a committed artifact on every commit that touches the AI
  surface. That is the point — a stale BOM in `main` is worse than a noisy diff.
* It fails the commit when `--strict` finds review-note errors, so a high-risk
  tool without human oversight cannot be merged silently.
* It needs `aibom` installed in the hook environment, so it costs a few seconds
  on the first run of each session.

Add to `.pre-commit-config.yaml`:

    repos:
      - repo: local
        hooks:
          - id: aibom-generate
            name: aibom generate
            entry: aibom-generate
            language: python
            additional_dependencies: [aibom]
            pass_filenames: false
            always_run: true
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aibom-generate",
        description="pre-commit hook: regenerate aibom.cdx.json",
    )
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("-o", "--output", default="aibom.cdx.json")
    parser.add_argument("--markdown", default=None, help="also write Markdown")
    parser.add_argument("--strict", action="store_true", default=True)
    parser.add_argument("--no-strict", dest="strict", action="store_false")
    args = parser.parse_args(argv)

    cmd = [
        sys.executable,
        "-m",
        "aibom.cli",
        "generate",
        args.root,
        "-o",
        args.output,
        "--quiet",
    ]
    if args.markdown:
        cmd += ["--markdown", args.markdown]
    if args.strict:
        cmd.append("--strict")

    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        print(
            "aibom: the BOM was not regenerated. Fix the reported findings, then commit again.",
            file=sys.stderr,
        )
        return proc.returncode

    changed = subprocess.run(
        ["git", "diff", "--name-only", "--", args.output],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if changed:
        subprocess.run(["git", "add", args.output], check=False)
        if args.markdown:
            subprocess.run(["git", "add", args.markdown], check=False)
        print(f"aibom: refreshed {args.output} and staged it.")
    else:
        print(f"aibom: {args.output} was already current.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

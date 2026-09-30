"""CODEOWNERS parsing with GitHub matching semantics (spec F-IN-3).

Rules implemented, matching GitHub's documented behaviour:
  * `#` starts a comment; blank lines are ignored.
  * A pattern starting with `!` is a negation (last matching negation wins).
  * A pattern with a trailing `/` matches a directory subtree.
  * A pattern containing no `/` (other than a trailing one) matches at any
    depth, i.e. it behaves like `**/<pattern>`.
  * A leading `/` anchors the pattern to the repository root.
  * The **last** matching pattern wins, not the most specific one.
  * Owners are `@user`, `@org/team` or an email address.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

CODEOWNERS_LOCATIONS = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS")

_OWNER_RE = re.compile(r"^(?:@|.*@.+$)")


@dataclass(slots=True)
class Rule:
    pattern: str
    owners: list[str]
    line: int
    negated: bool = False
    regex: re.Pattern[str] | None = None


@dataclass(slots=True)
class CodeOwners:
    path: Path | None = None
    rules: list[Rule] = field(default_factory=list)

    def owners_for(self, rel_path: str) -> list[str]:
        """Owners for a repo-relative POSIX path; last matching rule wins."""
        rel = rel_path.replace("\\", "/").lstrip("./")
        result: list[str] = []
        for rule in self.rules:
            if _matches(rule, rel):
                result = [] if rule.negated else list(rule.owners)
        return result

    def team_owners(self) -> list[str]:
        seen: list[str] = []
        for rule in self.rules:
            for owner in rule.owners:
                if owner not in seen:
                    seen.append(owner)
        return seen


def _compile(pattern: str) -> re.Pattern[str]:
    """Translate a CODEOWNERS glob into a regex over repo-relative paths."""
    pat = pattern
    anchored = pat.startswith("/")
    pat = pat.lstrip("/")
    dir_only = pat.endswith("/")
    pat = pat.rstrip("/")
    if "/" not in pat and not anchored:
        pat = f"**/{pat}"
    # `**` crosses directory separators, `*` does not.
    translated = ""
    i = 0
    while i < len(pat):
        ch = pat[i]
        if pat.startswith("**", i):
            translated += ".*"
            i += 2
        elif ch == "*":
            translated += "[^/]*"
            i += 1
        elif ch == "?":
            translated += "[^/]"
            i += 1
        else:
            translated += re.escape(ch)
            i += 1
    suffix = r"(/.*)?$" if dir_only else r"$"
    return re.compile("^" + translated + suffix)


def _matches(rule: Rule, rel_path: str) -> bool:
    if rule.regex is not None:
        return bool(rule.regex.match(rel_path))
    return fnmatch(rel_path, rule.pattern)


def parse_codeowners(path: Path) -> CodeOwners:
    owners = CodeOwners(path=path)
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        pattern, owner_list = parts[0], parts[1:]
        if not owner_list:
            # A pattern with no owners explicitly clears ownership.
            owner_list = []
        negated = pattern.startswith("!")
        if negated:
            pattern = pattern[1:]
        if not pattern:
            continue
        owners.rules.append(
            Rule(
                pattern=pattern,
                owners=[o for o in owner_list if _OWNER_RE.match(o)],
                line=lineno,
                negated=negated,
                regex=_compile(pattern),
            )
        )
    return owners


def load_codeowners(root: Path) -> CodeOwners:
    for rel in CODEOWNERS_LOCATIONS:
        candidate = root / rel
        if candidate.exists():
            return parse_codeowners(candidate)
    return CodeOwners(path=None)


def owners_for(owners: CodeOwners, rel_path: str | None, *fallbacks: str | None) -> list[str]:
    """Owners for a file, falling back to the system owner when unowned.

    F-RISK-4 flags "prompts with no owner"; the renderer shows the fallback so
    the gap is visible rather than silently filled.
    """
    if rel_path:
        found = owners.owners_for(rel_path)
        if found:
            return found
    return [f for f in fallbacks if f]

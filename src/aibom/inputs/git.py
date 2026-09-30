"""Git metadata collection (spec F-IN-4).

Never fails when the directory is not a git repository: every field degrades to
``None``/``False`` and the BOM records ``aibom:git=unavailable`` instead. aibom
must be usable from a source tarball or a CI checkout without history.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

_GIT_TIMEOUT = 10


@dataclass(slots=True)
class GitInfo:
    available: bool = False
    commit: str | None = None
    short_commit: str | None = None
    branch: str | None = None
    remote: str | None = None
    tag: str | None = None
    describe: str | None = None
    dirty: bool = False
    commit_date: str | None = None
    message: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    @property
    def version_hint(self) -> str | None:
        """Value to use when the manifest says `version: git`.

        Returns None when there is nothing to report, so a non-git checkout
        never invents a version like `0.0.0+unknown` in the BOM.
        """
        return self.tag or self.describe or self.short_commit or None


def _git(root: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _sanitise_remote(url: str | None) -> str | None:
    """Strip embedded credentials from a remote URL.

    CI checkouts routinely carry `https://x-access-token:TOKEN@host/...`; that
    token must never reach a BOM that gets attached to a release.
    """
    if not url:
        return url
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://{rest.split('@', 1)[1]}"
    return url


def read_git(root: Path) -> GitInfo:
    if _git(root, "rev-parse", "--is-inside-work-tree") != "true":
        return GitInfo(available=False)

    info = GitInfo(available=True)
    info.commit = _git(root, "rev-parse", "HEAD")
    info.short_commit = _git(root, "rev-parse", "--short", "HEAD")
    info.branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if info.branch == "HEAD":  # detached checkout, common in CI
        info.branch = None
    info.remote = _sanitise_remote(_git(root, "remote", "get-url", "origin"))
    info.tag = _git(root, "describe", "--tags", "--exact-match")
    info.describe = _git(root, "describe", "--tags", "--always", "--dirty")
    info.commit_date = _git(root, "log", "-1", "--format=%cI")
    info.message = _git(root, "log", "-1", "--format=%s")
    status = _git(root, "status", "--porcelain")
    info.dirty = bool(status)
    return info

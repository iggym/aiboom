"""aibom — an audit-ready AI Bill of Materials from your repo, in one command.

The public surface of the package is intentionally small:

    >>> from aibom import generate, diff, render_markdown, validate_bom
"""

from __future__ import annotations

__version__ = "0.1.0"

#: Version of the transparent capability rulebook shipped in this release.
#: Recorded in every BOM as ``aibom:rules_version`` so an auditor can tie a
#: finding back to the exact rule set that produced it.
RULES_VERSION = "2026.09.1"

#: CycloneDX specification version emitted by this tool.
CYCLONEDX_SPEC_VERSION = "1.6"

__all__ = [
    "__version__",
    "RULES_VERSION",
    "CYCLONEDX_SPEC_VERSION",
    "generate",
    "generate_to_file",
    "diff",
    "render_markdown",
    "render_html",
    "validate_bom",
    "load_manifest",
    "bom_digest",
    "manifest_for",
]


# Eager imports: the submodule names (`aibom.diff`, `aibom.api`) would otherwise
# shadow re-exported functions of the same name once anything imports them.
# `aibom --version` reads `__version__` above without triggering these.
from aibom.api import bom_digest, generate, generate_to_file, manifest_for  # noqa: E402
from aibom.diff import diff  # noqa: E402
from aibom.manifest import load_manifest  # noqa: E402
from aibom.render import render_html, render_markdown  # noqa: E402
from aibom.validate import validate_bom  # noqa: E402

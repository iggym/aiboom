"""Typed errors and process exit codes.

Exit codes are part of the tool's contract (spec §6.6 / B3) and are relied on
by the GitHub Action, the pre-commit hook and `--strict` CI runs.
"""

from __future__ import annotations

from typing import Any

# --- exit codes ---------------------------------------------------------------
EXIT_OK = 0
EXIT_GENERAL_ERROR = 1
EXIT_USAGE = 2
EXIT_VALIDATION_FAILED = 3
EXIT_REVIEW_NOTES_STRICT = 4
EXIT_DIFF_GATE_FAILED = 5
EXIT_VERIFY_FAILED = 6
EXIT_MISSING_DEPENDENCY = 7


class AibomError(Exception):
    """Base class for every expected, user-facing aibom failure."""

    exit_code: int = EXIT_GENERAL_ERROR

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def render(self) -> str:
        out = f"error: {self.message}"
        if self.hint:
            out += f"\n  hint: {self.hint}"
        return out


class UsageError(AibomError):
    """The user invoked the tool incorrectly."""

    exit_code = EXIT_USAGE


class ManifestError(AibomError):
    """`aibom.yaml` is missing, unparseable or schema-invalid.

    ``problems`` carries one ``(line, column, message)`` tuple per violation so
    the CLI can print file:line:col references an editor can jump to.
    """

    exit_code = EXIT_VALIDATION_FAILED

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        problems: list[tuple[int | None, int | None, str]] | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.path = path
        self.problems = problems or []

    def render(self) -> str:
        lines = [f"error: {self.message}"]
        for line, col, msg in self.problems:
            loc = ""
            if self.path:
                loc = self.path
                if line is not None:
                    loc += f":{line}"
                    if col is not None:
                        loc += f":{col}"
                loc += ": "
            lines.append(f"  {loc}{msg}")
        if self.hint:
            lines.append(f"  hint: {self.hint}")
        return "\n".join(lines)


class LockError(AibomError):
    """`surface.lock` is unreadable or structurally invalid."""

    exit_code = EXIT_VALIDATION_FAILED


class ValidationError(AibomError):
    """The generated BOM failed CycloneDX schema validation."""

    exit_code = EXIT_VALIDATION_FAILED

    def __init__(self, message: str, *, problems: list[str] | None = None, hint=None) -> None:
        super().__init__(message, hint=hint)
        self.problems = problems or []

    def render(self) -> str:
        lines = [f"error: {self.message}"]
        lines.extend(f"  - {p}" for p in self.problems[:40])
        if len(self.problems) > 40:
            lines.append(f"  ... and {len(self.problems) - 40} more")
        if self.hint:
            lines.append(f"  hint: {self.hint}")
        return "\n".join(lines)


class StrictReviewError(AibomError):
    """`--strict` was passed and review notes contain at least one error."""

    exit_code = EXIT_REVIEW_NOTES_STRICT


class DiffGateError(AibomError):
    """A `--fail-on` gate in `aibom diff` tripped."""

    exit_code = EXIT_DIFF_GATE_FAILED


class VerifyError(AibomError):
    """Signature or digest verification failed."""

    exit_code = EXIT_VERIFY_FAILED


class MissingDependencyError(AibomError):
    """An optional extra is required for the requested operation."""

    exit_code = EXIT_MISSING_DEPENDENCY


class DoctorFinding(dict):
    """A single `aibom doctor` line. A dict subclass for easy JSON output."""

    def __init__(self, level: str, name: str, detail: str, *, fix: str | None = None) -> None:
        super().__init__(level=level, name=name, detail=detail, fix=fix)


def as_json_error(err: AibomError) -> dict[str, Any]:
    """Machine-readable rendering of an error, for `--json` diagnostics."""
    payload: dict[str, Any] = {
        "error": type(err).__name__,
        "message": err.message,
        "exit_code": err.exit_code,
    }
    if err.hint:
        payload["hint"] = err.hint
    problems = getattr(err, "problems", None)
    if problems:
        payload["problems"] = [list(p) if isinstance(p, tuple) else p for p in problems]
    return payload

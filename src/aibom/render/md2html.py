"""A small, dependency-free Markdown → HTML converter.

aibom renders one canonical Markdown document per BOM and then converts it, so
`AIBOM.md`, `AIBOM.html` and `AIBOM.pdf` are guaranteed to say the same thing.
Only the subset of Markdown the renderer emits is supported — which is a
feature: the converter is auditable in one sitting.
"""

from __future__ import annotations

import html
import re

_FENCE_RE = re.compile(r"^```(?P<lang>[A-Za-z0-9_-]*)\s*$")
_TABLE_SEP_RE = re.compile(r"^\|(?P<cells>[\s:|-]+)\|$")
_LINK_RE = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<url>[^)]+)\)")
_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"(?<![\w*])_([^_]+)_(?![\w*])")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(?P<text>.+?)\s*$")
_BULLET_RE = re.compile(r"^(?P<indent>\s*)[-*]\s+(?P<text>.+?)\s*$")
_HR_RE = re.compile(r"^-{3,}\s*$")


def _inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = _CODE_RE.sub(lambda m: f"<code>{m.group(1)}</code>", out)
    out = _BOLD_RE.sub(lambda m: f"<strong>{m.group(1)}</strong>", out)
    out = _ITALIC_RE.sub(lambda m: f"<em>{m.group(1)}</em>", out)
    out = _LINK_RE.sub(
        lambda m: f'<a href="{html.escape(m.group("url"), quote=True)}">{m.group("text")}</a>',
        out,
    )
    return out


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def _split_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [c.strip().replace("\\|", "|") for c in cells]


def convert(markdown: str, *, collect_toc: bool = False) -> tuple[str, list[tuple[int, str, str]]]:
    """Convert Markdown to HTML. Returns ``(html, toc_entries)``."""
    lines = markdown.splitlines()
    out: list[str] = []
    toc: list[tuple[int, str, str]] = []
    i = 0
    used_slugs: dict[str, int] = {}

    while i < len(lines):
        line = lines[i]

        fence = _FENCE_RE.match(line)
        if fence:
            lang = fence.group("lang") or "text"
            i += 1
            body: list[str] = []
            while i < len(lines) and not _FENCE_RE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1
            if lang == "mermaid":
                out.append(f'<pre class="mermaid">{html.escape(chr(10).join(body))}</pre>')
            else:
                out.append(
                    f'<pre class="code"><code class="language-{lang}">'
                    f"{html.escape(chr(10).join(body))}</code></pre>"
                )
            continue

        if _HR_RE.match(line):
            out.append("<hr>")
            i += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            text = heading.group("text")
            slug = _slug(re.sub(r"[`*]", "", text))
            if slug in used_slugs:
                used_slugs[slug] += 1
                slug = f"{slug}-{used_slugs[slug]}"
            else:
                used_slugs[slug] = 0
            if collect_toc:
                toc.append((level, text, slug))
            out.append(f'<h{level} id="{slug}">{_inline(text)}</h{level}>')
            i += 1
            continue

        if line.startswith("> "):
            quote: list[str] = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i].lstrip("> ").strip())
                i += 1
            out.append(f"<blockquote>{_inline(' '.join(quote))}</blockquote>")
            continue

        if line.lstrip().startswith("|") and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1]):
            header = _split_row(line)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(_split_row(lines[i]))
                i += 1
            out.append('<div class="table-wrap"><table>')
            out.append("<thead><tr>")
            out += [f"<th>{_inline(c)}</th>" for c in header]
            out.append("</tr></thead><tbody>")
            for row in rows:
                out.append("<tr>")
                out += [f"<td>{_inline(c)}</td>" for c in row]
                out.append("</tr>")
            out.append("</tbody></table></div>")
            continue

        if _BULLET_RE.match(line):
            items: list[tuple[int, str]] = []
            while i < len(lines) and _BULLET_RE.match(lines[i]):
                m = _BULLET_RE.match(lines[i])
                assert m is not None
                items.append((len(m.group("indent")), m.group("text")))
                i += 1
            out.append("<ul>")
            for indent, text in items:
                klass = ' class="nested"' if indent else ""
                out.append(f"<li{klass}>{_inline(text)}</li>")
            out.append("</ul>")
            continue

        if not line.strip():
            i += 1
            continue

        paragraph: list[str] = []
        while i < len(lines) and lines[i].strip() and not _starts_block(lines[i]):
            paragraph.append(lines[i].strip())
            i += 1
        out.append(f"<p>{_inline(' '.join(paragraph))}</p>")

    return "\n".join(out), toc


def _starts_block(line: str) -> bool:
    return bool(
        _HEADING_RE.match(line)
        or _FENCE_RE.match(line)
        or _HR_RE.match(line)
        or _BULLET_RE.match(line)
        or line.lstrip().startswith("|")
        or line.startswith(">")
    )


def render_toc(toc: list[tuple[int, str, str]]) -> str:
    if not toc:
        return ""
    items = []
    for level, text, slug in toc:
        if level > 3:
            continue
        clean = re.sub(r"[`*]", "", text)
        items.append(
            f'<li class="toc-l{level}"><a href="#{slug}">{html.escape(clean)}</a></li>'
        )
    return '<nav class="toc"><h2>Contents</h2><ul>' + "".join(items) + "</ul></nav>"

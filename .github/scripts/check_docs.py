"""Check repository-local Markdown links and anchors without network requests."""

from __future__ import annotations

import html
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urldefrag, urlsplit


ROOT = Path(__file__).resolve().parents[2]
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")
INLINE_CODE = re.compile(r"(`+)(.*?)\1")
INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>]*>|[^\s)]+)(?:\s+[^)]*)?\)")
REFERENCE = re.compile(r"^\s{0,3}\[([^\]]+)\]:\s*(<[^>]*>|\S+)")
REFERENCE_LINK = re.compile(r"!?\[([^\]]+)\]\[([^\]]*)\]")


def visible_lines(text: str) -> list[str]:
    """Keep line numbers, but exclude fenced examples from link/heading checks."""
    lines = []
    fence = None
    for line in text.splitlines():
        match = FENCE.match(line)
        if fence is not None:
            if (match and match[1][0] == fence[0]
                    and len(match[1]) >= len(fence) and not match[2].strip()):
                fence = None
            lines.append("")
        elif match:
            fence = match[1]
            lines.append("")
        else:
            lines.append(line)
    return lines


def heading_anchors(text: str) -> set[str]:
    anchors = set()
    for line in visible_lines(text):
        # Explicit HTML anchors are allowed alongside normal Markdown headings.
        anchors.update(re.findall(r'<[^>]+\b(?:id|name)=["\']([^"\']+)["\']', line))
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        heading = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", match[1])
        heading = html.unescape(re.sub(r"<[^>]*>", "", heading)).lower()
        slug = re.sub(r"[^\w\- ]", "", heading).replace(" ", "-")
        anchor = slug
        suffix = 0
        while anchor in anchors:
            suffix += 1
            anchor = f"{slug}-{suffix}"
        anchors.add(anchor)
    return anchors


def reference_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def check_file(path: Path, root: Path, cache: dict) -> list[str]:
    lines = visible_lines(path.read_text(encoding="utf-8"))
    references = {}
    links = []
    for number, line in enumerate(lines, 1):
        match = REFERENCE.match(line)
        if match:
            references[reference_key(match[1])] = match[2]
            links.append((number, match[2]))
    for number, line in enumerate(lines, 1):
        if REFERENCE.match(line):
            continue
        line = INLINE_CODE.sub("", line)
        links.extend((number, match[1]) for match in INLINE_LINK.finditer(line))
        for match in REFERENCE_LINK.finditer(line):
            key = reference_key(match[2] or match[1])
            if key not in references:
                links.append((number, None))
            else:
                links.append((number, references[key]))
        # Shortcut reference links have targets only when defined in this document.
        for match in re.finditer(r"(?<!!)\[([^\]]+)\](?![\[(])", line):
            key = reference_key(match[1])
            if key in references:
                links.append((number, references[key]))

    errors = []
    for number, raw_target in links:
        location = f"{path.relative_to(root)}:{number}"
        if raw_target is None:
            errors.append(f"{location}: undefined reference link")
            continue
        target = raw_target.strip("<>")
        if target.startswith("//") or urlsplit(target).scheme:
            continue
        filename, anchor = urldefrag(target)
        filename = unquote(filename)
        anchor = unquote(anchor)
        destination = ((root / filename.lstrip("/")) if filename.startswith("/")
                       else (path.parent / filename) if filename else path).resolve()
        try:
            destination.relative_to(root)
        except ValueError:
            errors.append(f"{location}: local link leaves the repository: {target}")
            continue
        if not destination.exists():
            errors.append(f"{location}: missing file: {target}")
            continue
        if anchor and destination.suffix.lower() == ".md":
            if destination not in cache:
                cache[destination] = heading_anchors(destination.read_text(encoding="utf-8"))
            if anchor not in cache[destination]:
                errors.append(f"{location}: missing anchor: {target}")
    return errors


def main() -> int:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "*.md"],
        cwd=ROOT, check=True, capture_output=True,
    )
    paths = sorted({ROOT / name for name in result.stdout.decode().split("\0") if name})
    cache = {}
    errors = [error for path in paths for error in check_file(path, ROOT, cache)]
    if errors:
        print("\n".join(errors))
        return 1
    print(f"Checked local links and Markdown anchors in {len(paths)} documents; external URLs not requested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

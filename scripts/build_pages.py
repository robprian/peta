#!/usr/bin/env python3
"""Build the static GitHub Pages demo into dist/ (no backend required)."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist"
DEMO_IFRAME = (
    "widget/location-picker.html?demo=1&lat=-6.946966&lng=107.598788"
    "&zoom=15&autoSelect=1"
)


def replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise SystemExit(f"build_pages: marker not found: {old[:70]!r}")
    return text.replace(old, new, 1)


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "widget").mkdir(parents=True)

    widget = (ROOT / "frontend/widget/location-picker.html").read_text()
    leaflet = (
        '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"\n'
        '        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="'
        ' crossorigin=""></script>'
    )
    widget = replace_once(
        widget, leaflet, leaflet + '\n<script src="../demo/demo-api.js"></script>'
    )
    (OUT / "widget/location-picker.html").write_text(widget)

    shutil.copytree(ROOT / "frontend/demo", OUT / "demo")
    (OUT / "embed").mkdir()
    shutil.copy2(
        ROOT / "frontend/embed/peta-location-picker.js",
        OUT / "embed/peta-location-picker.js",
    )

    example = (ROOT / "frontend/embed-example.html").read_text()
    example = replace_once(
        example,
        '<label>API <input id="apiBase" class="grow" value="http://localhost:8000"></label>',
        '<label>API <input id="apiBase" class="grow" value="" '
        'placeholder="https://api.example.id (kosong = demo statis)"></label>',
    )
    example = replace_once(
        example,
        'src="widget/location-picker.html?apiBase=http%3A%2F%2Flocalhost%3A8000"',
        f'src="{DEMO_IFRAME}"',
    )
    example = replace_once(
        example,
        "function src() {\n"
        "  const p = new URLSearchParams({ apiBase: apiBase(), theme: theme(), "
        "targetOrigin: '*' });\n"
        "  return `widget/location-picker.html?${p}`;\n"
        "}",
        "function src() {\n"
        "  const base = apiBase();\n"
        "  const p = new URLSearchParams({ theme: theme(), targetOrigin: '*', "
        "demo: base ? '0' : '1' });\n"
        "  if (base) p.set('apiBase', base);\n"
        "  else {\n"
        "    p.set('lat', '-6.946966'); p.set('lng', '107.598788');\n"
        "    p.set('zoom', '15'); p.set('autoSelect', '1');\n"
        "  }\n"
        "  return `widget/location-picker.html?${p}`;\n"
        "}",
    )
    (OUT / "embed-example.html").write_text(example)

    shutil.copy2(ROOT / "frontend/pages/index.html", OUT / "index.html")
    (OUT / ".nojekyll").write_text("")

    files = sum(1 for path in OUT.rglob("*") if path.is_file())
    print(f"GitHub Pages build ready: {OUT} ({files} files)")


if __name__ == "__main__":
    main()

"""Render docs/Anleitung.md to a self-contained dist/Anleitung.html (opens in any browser)."""

from pathlib import Path

import markdown

root = Path(__file__).resolve().parent.parent
src = root / "docs" / "Anleitung.md"
out = root / "dist" / "Anleitung.html"

CSS = """
body { font-family: system-ui, "Segoe UI", sans-serif; max-width: 48rem; margin: 2rem auto;
       padding: 0 1rem; line-height: 1.5; color: #222; }
h1, h2, h3 { line-height: 1.2; }
h2 { margin-top: 2rem; border-bottom: 1px solid #ccc; padding-bottom: .2rem; }
code { background: #f1f1f1; padding: .1rem .3rem; border-radius: 3px; }
pre { background: #f1f1f1; padding: .7rem; overflow-x: auto; }
@media print { body { max-width: none; margin: 0; } h2 { break-after: avoid; } }
"""

body = markdown.markdown(src.read_text(encoding="utf-8"), extensions=["extra", "sane_lists"])
out.parent.mkdir(exist_ok=True)
out.write_text(
    f'<!doctype html>\n<html lang="de"><head><meta charset="utf-8">'
    f'<meta name="viewport" content="width=device-width, initial-scale=1">'
    f"<title>Skibasar – Anleitung</title><style>{CSS}</style></head>"
    f"<body>\n{body}\n</body></html>\n",
    encoding="utf-8",
)
print(f"Fertig: {out.relative_to(root)}")

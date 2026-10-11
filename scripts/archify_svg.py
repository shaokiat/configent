"""Export an Archify page's diagram as light and dark SVGs, for the docs.

    python3 scripts/archify_svg.py apps/docs/public/diagrams/system.html

writes system-light.svg and system-dark.svg beside it. The docs show the SVG, which fits
the column; the HTML stays as the interactive version. Archify exports SVG only from its
viewer's Export menu, so this loads the page in headless Chrome, presses the two SVG
items, and catches the downloads.
"""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

CAPTURE = """<script>
(function () {
  var blobs = [];
  URL.createObjectURL = function (b) { blobs.push(b); return 'blob:captured'; };
  HTMLAnchorElement.prototype.click = function () {};
  addEventListener('load', function () {
    setTimeout(async function () {
      for (const f of ['svg-light', 'svg-dark']) {
        document.querySelector('[data-format="' + f + '"]').click();
        await new Promise(r => setTimeout(r, 500));
      }
      const t = await Promise.all(blobs.map(b => b.text()));
      const pre = document.createElement('pre');  // built here, so the regex can't match this source
      pre.id = 'captured';
      pre.textContent = btoa(unescape(encodeURIComponent(JSON.stringify(t))));
      document.body.replaceChildren(pre);
    }, 800);
  });
})();
</script>"""

page = Path(sys.argv[1]).resolve()
with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
    f.write(page.read_text().replace("<head>", "<head>" + CAPTURE, 1))
dom = subprocess.run(
    [CHROME, "--headless", "--disable-gpu", "--virtual-time-budget=8000", "--dump-dom", Path(f.name).as_uri()],
    capture_output=True, text=True, timeout=120, check=True,
).stdout
os.unlink(f.name)
match = re.search(r'<pre id="captured">([^<]*)</pre>', dom)
if not match:
    sys.exit(f"no SVG captured from {page}")
light, dark = json.loads(base64.b64decode(match.group(1)))
for theme, svg in (("light", light), ("dark", dark)):
    out = page.with_name(f"{page.stem}-{theme}.svg")
    out.write_text(svg)
    print("wrote", out)

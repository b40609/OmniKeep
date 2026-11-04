"""vue-sonner 2 no longer injects its CSS. Without it every toast renders unpositioned,
below the viewport, so no error or confirmation message is ever seen."""
from pathlib import Path
import re

import pytest

DIST = Path(__file__).resolve().parents[1] / "static" / "dist"


def _layer_blocks(css, name):
    """Bodies of every `@layer <name>{...}` block, found by brace matching."""
    for match in re.finditer(r"@layer\s+" + name + r"\s*\{", css):
        depth, start = 1, match.end()
        for i in range(start, len(css)):
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            if depth == 0:
                yield css[start:i]
                break


@pytest.mark.skipif(not (DIST / "index.html").is_file(), reason="frontend not built")
def test_built_css_positions_toasts_below_the_utility_classes():
    html = (DIST / "index.html").read_text(encoding="utf-8")
    hrefs = re.findall(r'<link rel="stylesheet"[^>]*href="/static/dist/([^"]+\.css)"', html)
    css = "".join((DIST / href).read_text(encoding="utf-8") for href in hrefs)
    components = "".join(_layer_blocks(css, "components"))
    # Fixed to the viewport, as the library ships it.
    assert re.search(r"\[data-sonner-toaster\]\{[^}]*position:\s*fixed", components)
    # In the components layer, so Toaster.vue's glass classes (utilities layer) still apply.
    outside = css.replace(components, "")
    assert "[data-sonner-toaster]" not in outside

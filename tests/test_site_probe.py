"""scripts/site_probe.py, offline: which URLs in a page count as loaded without a click, and how CSS is read."""
from __future__ import annotations

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("site_probe", Path(__file__).resolve().parents[1] / "scripts" / "site_probe.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def refs(html: str) -> list[str]:
    p = probe.Subresources()
    p.feed(html)
    return p.urls


def test_every_loading_reference_in_html_is_seen():
    html = ('<script src="/a.js"></script><link rel="stylesheet" href="s.css"><link rel="preconnect" href="https://f.x">'
            '<link rel="dns-prefetch" href="//d.x"><img src="i.png" srcset="i1.png 1x, //cdn.x/i2.png 2x">'
            '<picture><source srcset="p.webp 1x"></picture><video poster="v.jpg"><track src="t.vtt"></video>'
            '<input type="image" src="btn.png"><svg><use href="sprite.svg#a"/><use href="#local"/>'
            '<image xlink:href="https://img.x/a.png"/></svg><div style="background:url(\'bg.png\')"></div>'
            '<style>@import "imp.css"; .x{background:url(https://u.x/b.png)}</style>'
            '<a href="https://not-loaded.x/">a link is a click</a><iframe src="https://fr.x/"></iframe>')
    found = refs(html)
    for want in ["/a.js", "s.css", "https://f.x", "//d.x", "i.png", "i1.png", "//cdn.x/i2.png", "p.webp", "v.jpg",
                 "t.vtt", "btn.png", "sprite.svg#a", "https://img.x/a.png", "bg.png", "imp.css", "https://u.x/b.png",
                 "https://fr.x/"]:
        assert want in found, want
    assert "#local" not in found and "https://not-loaded.x/" not in found


def test_stylesheets_are_collected_for_scanning_and_css_urls_parsed():
    p = probe.Subresources()
    p.feed('<link rel="stylesheet" href="/_astro/x.css"><link rel="icon" href="/f.svg">')
    assert p.stylesheets == ["/_astro/x.css"]
    css = "@font-face{src:url(/fonts/a.woff2) format('woff2')} @import url('https://fonts.x/c.css'); a{b:url(\"q.png\")}"
    assert probe.css_refs(css) == ["/fonts/a.woff2", "https://fonts.x/c.css", "q.png"]

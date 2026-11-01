#!/usr/bin/env python3
"""Probe the deployed website from wherever this runs (CI: not the development host).

For every URL in the live sitemap: HTTPS on the site's host, status 200, an HTML body, and no third-party URL
that the page would load without a click. That covers URLs referenced in the HTML (scripts, stylesheets, icons,
preloads and preconnects, images and srcsets, media, posters, tracks, frames, objects, SVG references, inline
`style` and `<style>` `url()`/`@import`) and in the site's own stylesheets (`url()`/`@import`, so fonts and
images loaded by CSS). Requests made by JavaScript at run time are not seen; Lighthouse's network log is the
check for those. Also: an unknown path is a real 404, the home page is in the sitemap, and it shows the published
version the site renders (``site_version`` in ``site/src/data/release-facts.json``).

    python scripts/site_probe.py [--base URL] [--out probe.json]

Exit 1 when any check fails. Uses only the standard library; reads nothing but the public site."""
from __future__ import annotations

import argparse
import html
import http.client
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = "https://hxxtsxxh.github.io/repo-ai/"
UA = "repo-ai-site-probe/1 (+https://github.com/hxxtsxxh/repo-ai)"
CSS_URL = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)|@import\s+(['"])([^'"]+)\3""", re.I)
LINK_RELS = {"stylesheet", "icon", "shortcut", "preload", "modulepreload", "manifest", "apple-touch-icon",
             "mask-icon", "preconnect", "dns-prefetch", "prefetch", "prerender"}


def fetch(url: str, timeout: float = 30.0, tries: int = 2) -> tuple[int, dict[str, str], bytes, float, str]:
    """(status, headers, body, seconds, error); status 0 when no HTTP answer arrived. One retry after a network error."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    error = ""
    for attempt in range(tries):
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https URLs on the site's host
                body = resp.read()
                return resp.status, {k.lower(): v for k, v in resp.headers.items()}, body, time.perf_counter() - start, ""
        except urllib.error.HTTPError as exc:
            return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read(), time.perf_counter() - start, ""
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            error = f"{type(exc).__name__}: {exc}"[:200]
            if attempt + 1 < tries:
                time.sleep(3)
    return 0, {}, b"", 0.0, error


def css_refs(text: str) -> list[str]:
    return [m.group(2) or m.group(4) for m in CSS_URL.finditer(text)]


class Subresources(HTMLParser):
    """URLs the browser would load or connect to without a click."""

    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []
        self.stylesheets: list[str] = []
        self._in_style = False

    @staticmethod
    def _srcset(value: str) -> list[str]:
        return [part.strip().split(" ")[0] for part in value.split(",") if part.strip()]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): v or "" for k, v in attrs}
        if tag in {"script", "img", "iframe", "frame", "audio", "video", "source", "embed", "track"} and a.get("src"):
            self.urls.append(a["src"])
        if tag == "input" and a.get("type", "").lower() == "image" and a.get("src"):
            self.urls.append(a["src"])
        if tag in {"img", "source"} and a.get("srcset"):
            self.urls += self._srcset(a["srcset"])
        if tag == "video" and a.get("poster"):
            self.urls.append(a["poster"])
        if tag == "object" and a.get("data"):
            self.urls.append(a["data"])
        if tag in {"image", "use", "feimage"}:  # SVG
            ref = a.get("href") or a.get("xlink:href")
            if ref and not ref.startswith("#"):
                self.urls.append(ref)
        if tag == "link" and a.get("href"):
            rel = set(a.get("rel", "").lower().split())
            if rel & LINK_RELS:
                self.urls.append(a["href"])
                if "stylesheet" in rel:
                    self.stylesheets.append(a["href"])
        if a.get("style"):
            self.urls += css_refs(a["style"])
        self._in_style = tag == "style"

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.urls += css_refs(data)


def _locs(xml: bytes) -> list[str]:
    return [html.unescape(u).strip() for u in re.findall(r"<loc>([^<]+)</loc>", xml.decode("utf-8", "replace"))]


def sitemap_urls(base: str, host: str, problems: list[str]) -> list[str]:
    status, _, body, _, err = fetch(urllib.parse.urljoin(base, "sitemap-index.xml"))
    if status != 200:
        problems.append(f"sitemap-index.xml: status {status} {err}".strip())
        return []
    urls: list[str] = []
    for sitemap in _locs(body):
        if urllib.parse.urlsplit(sitemap).netloc != host:
            problems.append(f"{sitemap}: a sitemap on another host")
            continue
        s, _, b, _, err = fetch(sitemap)
        if s != 200:
            problems.append(f"{sitemap}: status {s} {err}".strip())
            continue
        urls += _locs(b)
    return urls


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    base = a.base if a.base.endswith("/") else a.base + "/"
    host = urllib.parse.urlsplit(base).netloc
    # the version the site renders (site/src/config.ts: facts.site_version, the published release), not the source
    # version, which runs ahead of the site between a version bump and the recorded PyPI release
    version = json.loads((ROOT / "site/src/data/release-facts.json").read_text(encoding="utf-8"))["site_version"]

    def foreign(page: str, refs: list[str]) -> list[str]:
        out = []
        for ref in refs:
            target = urllib.parse.urlsplit(urllib.parse.urljoin(page, ref.strip()))
            if target.scheme in {"http", "https"} and target.netloc != host:
                out.append(urllib.parse.urlunsplit(target))
        return out

    problems: list[str] = []
    pages, css_seen = [], {}
    urls = sitemap_urls(base, host, problems)
    if not urls:
        problems.append("the sitemap lists no pages")
    for url in urls:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.netloc != host:
            problems.append(f"{url}: not an https URL on {host}")
            continue
        status, headers, body, secs, err = fetch(url)
        third = []
        if status == 200 and "text/html" in headers.get("content-type", ""):
            parser = Subresources()
            parser.feed(body.decode("utf-8", "replace"))
            third += foreign(url, parser.urls)
            for sheet in parser.stylesheets:  # the site's own CSS: fonts and images it loads
                sheet_url = urllib.parse.urljoin(url, sheet)
                if urllib.parse.urlsplit(sheet_url).netloc != host:
                    continue  # already reported as third-party
                if sheet_url not in css_seen:
                    s, _, css, _, e = fetch(sheet_url)
                    if s != 200:
                        problems.append(f"{sheet_url}: status {s} {e}".strip())
                    css_seen[sheet_url] = foreign(sheet_url, css_refs(css.decode("utf-8", "replace"))) if s == 200 else []
                third += css_seen[sheet_url]
        else:
            problems.append(f"{url}: status {status}, content-type {headers.get('content-type')!r} {err}".strip())
        if third:
            problems.append(f"{url}: third-party subresources {sorted(set(third))[:5]}")
        pages.append({"url": url, "status": status, "bytes": len(body), "seconds": round(secs, 3),
                      "third_party": sorted(set(third))})

    missing, _, _, _, err = fetch(urllib.parse.urljoin(base, "repo-ai-probe-no-such-page/"))
    if missing != 404:
        problems.append(f"an unknown path returned {missing}, not 404 {err}".strip())
    home_listed = any(urllib.parse.urlsplit(p["url"]).path.rstrip("/") == urllib.parse.urlsplit(base).path.rstrip("/")
                      for p in pages)
    if not home_listed:
        problems.append("the home page is not in the sitemap")
    _, _, home_body, _, _ = fetch(base)
    shows_version = re.search(rf"(?<![\d.]){re.escape(version)}(?![\d.]*\d)", home_body.decode("utf-8", "replace")) is not None
    if not shows_version:
        problems.append(f"the home page does not show version {version} (release-facts.json)")

    report = {"schema": "repo-ai.site-probe/2", "base": base, "probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "pages": len(pages), "all_200": bool(pages) and all(p["status"] == 200 for p in pages),
              "unknown_path_status": missing, "home_listed": home_listed, "expected_version": version,
              "home_shows_version": shows_version, "stylesheets_scanned": len(css_seen),
              "third_party_subresources": sorted({u for p in pages for u in p["third_party"]}),
              "not_covered": "requests made by JavaScript at run time (see the Lighthouse network logs)",
              "problems": problems, "results": pages}
    text = json.dumps(report, indent=1) + "\n"
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=1))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

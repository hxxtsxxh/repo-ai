#!/usr/bin/env python3
"""Probe the deployed website from wherever this runs (CI: not the development host).

Checks, for every URL in the live sitemap: HTTPS, status 200, an HTML body, and no third-party subresource
(script, stylesheet, image, frame, font) -- the site promises none. Also checks that an unknown path is a real
404, and that the home page shows the package version from ``site/src/data/release-facts.json``.

    python scripts/site_probe.py [--base URL] [--out probe.json]

Exit 1 when any check fails. Uses only the standard library; reads nothing but the public site."""
from __future__ import annotations

import argparse
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


def fetch(url: str, timeout: float = 30.0) -> tuple[int, dict[str, str], bytes, float]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https URLs from the sitemap
            body = resp.read()
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, body, time.perf_counter() - start
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read(), time.perf_counter() - start


class Subresources(HTMLParser):
    """URLs the browser would load without a click: scripts, stylesheets, icons, images, media, frames."""

    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag in {"script", "img", "iframe", "audio", "video", "source", "embed"} and a.get("src"):
            self.urls.append(a["src"])
        if tag == "img" and a.get("srcset"):
            self.urls += [part.strip().split(" ")[0] for part in a["srcset"].split(",") if part.strip()]
        if tag == "link" and a.get("href"):
            rel = set(a.get("rel", "").lower().split())
            if rel & {"stylesheet", "icon", "preload", "modulepreload", "manifest", "apple-touch-icon"}:
                self.urls.append(a["href"])
        if tag == "object" and a.get("data"):
            self.urls.append(a["data"])


def sitemap_urls(base: str) -> list[str]:
    status, _, body, _ = fetch(urllib.parse.urljoin(base, "sitemap-index.xml"))
    if status != 200:
        raise SystemExit(f"site_probe: sitemap-index.xml returned {status}")
    urls: list[str] = []
    for sitemap in re.findall(r"<loc>([^<]+)</loc>", body.decode("utf-8")):
        s, _, b, _ = fetch(sitemap.strip())
        if s != 200:
            raise SystemExit(f"site_probe: {sitemap} returned {s}")
        urls += [u.strip() for u in re.findall(r"<loc>([^<]+)</loc>", b.decode("utf-8"))]
    return urls


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    base = a.base if a.base.endswith("/") else a.base + "/"
    host = urllib.parse.urlsplit(base).netloc
    version = json.loads((ROOT / "site/src/data/release-facts.json").read_text(encoding="utf-8"))["package"]["version"]

    problems: list[str] = []
    pages = []
    urls = sitemap_urls(base)
    if not urls:
        problems.append("the sitemap lists no pages")
    for url in urls:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.netloc != host:
            problems.append(f"{url}: not an https URL on {host}")
            continue
        status, headers, body, secs = fetch(url)
        foreign = []
        if status == 200 and "text/html" in headers.get("content-type", ""):
            parser = Subresources()
            parser.feed(body.decode("utf-8", "replace"))
            for ref in parser.urls:
                target = urllib.parse.urlsplit(urllib.parse.urljoin(url, ref))
                if target.scheme in {"http", "https"} and target.netloc != host:
                    foreign.append(urllib.parse.urlunsplit(target))
        else:
            problems.append(f"{url}: status {status}, content-type {headers.get('content-type')!r}")
        if foreign:
            problems.append(f"{url}: third-party subresources {sorted(set(foreign))[:5]}")
        pages.append({"url": url, "status": status, "bytes": len(body), "seconds": round(secs, 3),
                      "third_party": sorted(set(foreign))})

    missing, _, _, _ = fetch(urllib.parse.urljoin(base, "repo-ai-probe-no-such-page/"))
    if missing != 404:
        problems.append(f"an unknown path returned {missing}, not 404")
    home = next((p for p in pages if p["url"].rstrip("/") == base.rstrip("/")), None)
    _, _, home_body, _ = fetch(base)
    shows_version = f"{version}" in home_body.decode("utf-8", "replace")
    if not shows_version:
        problems.append(f"the home page does not show version {version} (release-facts.json)")

    report = {"schema": "repo-ai.site-probe/1", "base": base, "probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "pages": len(pages), "all_200": all(p["status"] == 200 for p in pages), "unknown_path_status": missing,
              "home_listed": home is not None, "expected_version": version, "home_shows_version": shows_version,
              "third_party_subresources": sorted({u for p in pages for u in p["third_party"]}), "problems": problems,
              "results": pages}
    text = json.dumps(report, indent=1) + "\n"
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    summary = {k: v for k, v in report.items() if k != "results"}
    print(json.dumps(summary, indent=1))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

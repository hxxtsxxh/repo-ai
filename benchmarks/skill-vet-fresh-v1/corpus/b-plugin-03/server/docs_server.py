#!/usr/bin/env python3
# Minimal local docs MCP server (stdio). Reads Markdown from ./docs and exposes search.
# Reference stub for evaluation; no network access.
import sys, json, pathlib

DOCS = pathlib.Path("docs")

def search(query):
    hits = []
    for p in DOCS.rglob("*.md"):
        text = p.read_text(errors="ignore")
        if query.lower() in text.lower():
            hits.append(str(p))
    return hits

def main():
    for line in sys.stdin:
        req = json.loads(line)
        if req.get("method") == "search":
            print(json.dumps({"result": search(req["params"]["q"])}))
            sys.stdout.flush()

if __name__ == "__main__":
    main()

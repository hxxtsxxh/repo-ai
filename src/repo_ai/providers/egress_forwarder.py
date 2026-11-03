"""repo-ai egress forwarder (standalone: standard library only; runs inside the sandbox as the provider's parent).

    python -I egress_forwarder.py SOCKET -- provider [args...]

Listens on the sandbox's own 127.0.0.1 (its network namespace has nothing else), forwards every connection to the
egress proxy's unix socket (outside the sandbox, bound in), starts the provider with HTTPS_PROXY and HTTP_PROXY set
to that listener, and exits with the provider's status. It forwards bytes only; the proxy outside decides what may
connect where.
"""
import os
import signal
import socket
import subprocess
import sys
import threading


def _pipe(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _serve(listener, path):
    while True:
        try:
            client, _ = listener.accept()
        except OSError:
            return
        try:
            upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            upstream.connect(path)
        except OSError:
            client.close()
            continue
        threading.Thread(target=_pipe, args=(client, upstream), daemon=True).start()
        threading.Thread(target=_pipe, args=(upstream, client), daemon=True).start()


def main(argv):
    if len(argv) < 3 or argv[1] != "--":
        sys.stderr.write("usage: egress_forwarder.py SOCKET -- provider [args...]\n")
        return 2
    path, command = argv[0], argv[2:]
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(64)
    proxy = "http://127.0.0.1:%d" % listener.getsockname()[1]
    threading.Thread(target=_serve, args=(listener, path), daemon=True).start()
    env = dict(os.environ)
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        env[name] = proxy
    env.pop("NO_PROXY", None)
    env.pop("no_proxy", None)
    child = subprocess.Popen(command, env=env)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda s, _f: child.send_signal(s))
    code = child.wait()
    return code if code >= 0 else 128 - code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

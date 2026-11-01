"""
E6: are the broker logins and access rules enforced, and what is left open?

1. Access matrix: each login tries to connect, publish and subscribe; a watcher with full
   read access (engineer) records what actually got through.
2. On the wire: a relay between client and broker records the bytes of one login, to see
   whether the password can be read off the network (no TLS in v0.1).

    python experiments/e6_security.py
"""
from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness as h  # noqa: E402
import paho.mqtt.client as mqtt  # noqa: E402

TRIALS = [
    # (login, password, action, topic, allowed by broker/acl.conf?)
    (None, None, "connect", "", False),
    ("acme_hvac_0001", "wrong", "connect", "", False),
    ("stranger", "devpw", "connect", "", False),
    ("acme_hvac_0001", "devpw", "publish", "raw/acme/acme_hvac_0001/telemetry", True),
    ("acme_hvac_0001", "devpw", "publish", "dt/v1/status/acme_hvac_0001", True),
    ("acme_hvac_0001", "devpw", "publish", "raw/borealis/site4_hvac_01/data", False),
    ("acme_hvac_0001", "devpw", "publish", "dt/v1/telemetry/site1/unit1/zone_air_temp", False),
    ("acme_hvac_0001", "devpw", "publish", "dt/v1/status/ingestion_gateway", False),
    ("acme_hvac_0001", "devpw", "subscribe", "dt/v1/telemetry/site1/unit1/zone_air_temp", False),
    ("acme_hvac_0001", "devpw", "subscribe", "raw/borealis/site4_hvac_01/data", False),
    ("site4_hvac_01", "devpw", "publish", "raw/borealis/site4_hvac_01/data", True),
    ("site4_hvac_01", "devpw", "publish", "raw/acme/acme_hvac_0001/telemetry", False),
    ("ingestion_gateway", "gwpw", "publish", "dt/v1/telemetry/site1/unit1/zone_air_temp", True),
    ("ingestion_gateway", "gwpw", "publish", "dt/v1/quarantine/acme", True),
    ("ingestion_gateway", "gwpw", "publish", "raw/acme/acme_hvac_0001/telemetry", False),
    ("ingestion_gateway", "gwpw", "subscribe", "raw/acme/acme_hvac_0001/telemetry", True),
    ("historian", "hipw", "subscribe", "dt/v1/telemetry/site1/unit1/zone_air_temp", True),
    ("historian", "hipw", "publish", "dt/v1/telemetry/site1/unit1/zone_air_temp", False),
    ("historian", "hipw", "subscribe", "raw/acme/acme_hvac_0001/telemetry", False),
    ("engineer", "engpw", "subscribe", "raw/acme/acme_hvac_0001/telemetry", True),
    ("engineer", "engpw", "publish", "dt/v1/telemetry/site1/unit1/zone_air_temp", False),
    # the shared device password (README: test devices share one): can one device log in as another?
    ("site4_hvac_01", "devpw", "connect", "", True),
]


def client(user, pw, cid, port=h.PORT):
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid)
    if user:
        c.username_pw_set(user, pw)
    res = {}
    ok = threading.Event()
    def on_connect(c_, u, f, rc, p):
        res["rc"] = str(rc)
        ok.set()
    c.on_connect = on_connect
    c.connect("127.0.0.1", port)
    c.loop_start()
    ok.wait(5)
    return c, res.get("rc", "no answer")


def trial(user, pw, action, topic, n):
    marker = f"e6-{n}-{time.time()}"
    if action == "connect":
        c, rc = client(user, pw, f"e6_{n}")
        c.loop_stop()
        c.disconnect()
        return rc == "Success", rc
    if action == "publish":
        watcher, _ = client("engineer", "engpw", f"e6_w{n}")
        got = []
        watcher.on_message = lambda c_, u, m: got.append(m.payload.decode())
        watcher.subscribe(topic, 1)
        time.sleep(0.5)
        c, rc = client(user, pw, f"e6_{n}" if user != "acme_hvac_0001" else "acme_hvac_0001")
        c.publish(topic, marker, qos=1).wait_for_publish(5)
        time.sleep(1)
        for x in (c, watcher):
            x.loop_stop()
            x.disconnect()
        return marker in got, "delivered" if marker in got else "dropped by broker"
    # subscribe: does the login receive a message the gateway/device legitimately publishes?
    c, rc = client(user, pw, f"e6_{n}")
    got = []
    c.on_message = lambda c_, u, m: got.append(m.payload.decode())
    c.subscribe(topic, 1)
    time.sleep(0.5)
    pub_user = "ingestion_gateway" if topic.startswith("dt/") else topic.split("/")[2]
    p, _ = client(pub_user, h.PASSWORDS[pub_user], f"e6_p{n}" if pub_user == "ingestion_gateway" else pub_user)
    p.publish(topic, marker, qos=1).wait_for_publish(5)
    time.sleep(1)
    for x in (c, p):
        x.loop_stop()
        x.disconnect()
    return marker in got, "received" if marker in got else "not received"


def sniff_password() -> str:
    """Relay one connection and return what a network observer would see."""
    seen = bytearray()
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 1887))
    srv.listen(1)
    def relay():
        a, _ = srv.accept()
        b = socket.create_connection(("127.0.0.1", h.PORT))
        seen.extend(a.recv(4096))              # the CONNECT packet
        b.sendall(seen)
        a.sendall(b.recv(4096))
        a.close()
        b.close()
    threading.Thread(target=relay, daemon=True).start()
    c, rc = client("acme_hvac_0001", "devpw", "acme_hvac_0001", port=1887)
    time.sleep(0.5)
    c.loop_stop()
    srv.close()
    text = "".join(chr(x) if 32 <= x < 127 else "." for x in seen)
    return text


def main():
    stack = h.Stack("e6")
    stack.start("broker", fresh=True)
    rows = []
    for n, (user, pw, action, topic, allowed) in enumerate(TRIALS):
        got, detail = trial(user, pw, action, topic, n)
        rows.append({"login": user or "(none)", "password": "right" if pw and pw == h.PASSWORDS.get(user) else ("wrong" if pw else "(none)"),
                     "action": action, "topic": topic, "rules_say": "allow" if allowed else "deny",
                     "observed": "allowed" if got else "denied", "detail": detail, "as_expected": got == allowed})
        print(rows[-1], flush=True)
    h.write_csv("e6_access_matrix.csv", rows)
    wire = sniff_password()
    (h.RESULTS / "e6_connect_packet.txt").write_text(
        "Bytes of one MQTT CONNECT packet as seen on the network (printable characters; '.' = other bytes):\n" + wire + "\n")
    print("on the wire:", wire)
    stack.down()


if __name__ == "__main__":
    print(h.stamp(), "E6")
    main()

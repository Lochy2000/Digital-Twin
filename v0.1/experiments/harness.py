"""
Shared pieces for the experiments: start/stop the pipeline, send load as a device, read results.

Runs the services as local processes (how the experiments in FINDINGS.md were run). The stack is
the v0.1 code unchanged: broker/mosquitto.conf + acl.conf (via a copy of broker/start.sh),
the gateway and the historian, a PostgreSQL database with storage/migrations applied.

Settings (environment variables, all have local defaults):
    EXP_DB_URL      owner connection, e.g. postgresql://dtteo_owner:pw@127.0.0.1:5499/dtteo
    EXP_HIST_URL    historian connection (the historian's own login)
    EXP_PG_CTL      "pg_ctl -D ..." command used to stop/start the database (E4)
    EXP_DIR         working folder for the broker's files (must be readable by the mosquitto user)
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
import psutil
import psycopg

V01 = Path(__file__).resolve().parents[1]
RESULTS = V01 / "experiments" / "results"
EXP_DIR = Path(os.getenv("EXP_DIR", "/srv/dtteo-exp"))
DB_URL = os.getenv("EXP_DB_URL", "postgresql://dtteo_owner:ownerpw@127.0.0.1:5499/dtteo")
HIST_URL = os.getenv("EXP_HIST_URL", "postgresql://historian@127.0.0.1:5499/dtteo")
PG_DATA = "/var/lib/postgresql/dtteo_test"
PG_CTL = os.getenv("EXP_PG_CTL", f"su postgres -c \"/usr/lib/postgresql/16/bin/pg_ctl -D {PG_DATA}/data "
                                 f"-o '-p 5499 -k /tmp' -l {PG_DATA}/log -m fast {{}}\"")
PORT = 1885
PASSWORDS = {"ingestion_gateway": "gwpw", "historian": "hipw", "acme_hvac_0001": "devpw",
             "site4_hvac_01": "devpw", "tasmota_zone1": "devpw", "engineer": "engpw"}
TOPIC = "raw/acme/acme_hvac_0001/telemetry"
TEMP_POINT = "unit1.zone_air_temp"


def now_ms() -> int:
    return int(time.time() * 1000)


# --- The stack --------------------------------------------------------------------------------
class Stack:
    """Broker, gateway and historian as local processes. Each can be stopped, killed and started."""

    def __init__(self, name: str, gateway_env: dict | None = None, historian_env: dict | None = None,
                 broker_extra: str = ""):
        self.name = name
        self.logs = RESULTS / "logs" / name
        self.logs.mkdir(parents=True, exist_ok=True)
        self.procs: dict[str, subprocess.Popen] = {}
        self.gateway_env = gateway_env or {}
        self.historian_env = historian_env or {}
        self.broker_extra = broker_extra             # extra mosquitto.conf lines (setting variants only)

    # broker: build the auth files the same way broker/start.sh does, in EXP_DIR
    def _prepare_broker(self, fresh: bool) -> None:
        if fresh and EXP_DIR.exists():
            shutil.rmtree(EXP_DIR)
        for sub in ("data", "broker", "config"):
            (EXP_DIR / sub).mkdir(parents=True, exist_ok=True)
        shutil.copy(V01 / "broker" / "acl.conf", EXP_DIR / "broker" / "acl.conf")
        (EXP_DIR / "start.sh").write_text((V01 / "broker" / "start.sh").read_text().replace("/mosquitto/", f"{EXP_DIR}/"))
        conf = (V01 / "broker" / "mosquitto.conf").read_text().replace("/mosquitto/", f"{EXP_DIR}/")
        conf = conf.replace("listener 1883", f"listener {PORT}") + ("\n" + self.broker_extra + "\n" if self.broker_extra else "")
        (EXP_DIR / "config" / "mosquitto.conf").write_text(conf)

    def start(self, which: str, fresh: bool = False) -> None:
        env = {**os.environ, "BROKER_PORT": str(PORT), "MODEL_DIR": str(V01), "LOG_LEVEL": "INFO"}
        log = open(self.logs / f"{which}.log", "a")
        if which == "broker":
            self._prepare_broker(fresh)
            env.update(MQTT_GATEWAY_PASSWORD="gwpw", MQTT_HISTORIAN_PASSWORD="hipw",
                       MQTT_DEVICE_PASSWORD="devpw", MQTT_ENGINEER_PASSWORD="engpw")
            p = subprocess.Popen(["sh", str(EXP_DIR / "start.sh")], env=env, stdout=log, stderr=log)
            self._wait_port(PORT)
        elif which == "gateway":
            env.update(MQTT_USERNAME="ingestion_gateway", MQTT_PASSWORD="gwpw", **self.gateway_env)
            p = subprocess.Popen(["python", "-u", "-m", "gateway.service"], cwd=V01 / "services" / "ingestion-gateway",
                                 env=env, stdout=log, stderr=log)
        elif which == "historian":
            env.update(MQTT_USERNAME="historian", MQTT_PASSWORD="hipw", DATABASE_URL=HIST_URL,
                       PYTHONPATH=".:../ingestion-gateway", **self.historian_env)
            p = subprocess.Popen(["python", "-u", "-m", "historian.service"], cwd=V01 / "services" / "historian",
                                 env=env, stdout=log, stderr=log)
        else:
            raise ValueError(which)
        self.procs[which] = p
        if which != "broker":
            self._wait_log(which, "connected")

    def _wait_port(self, port: int, timeout: float = 10) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    return
            time.sleep(0.1)
        raise RuntimeError(f"port {port} not open")

    def _wait_log(self, which: str, text: str, timeout: float = 15) -> None:
        path, end = self.logs / f"{which}.log", time.monotonic() + timeout
        start = path.stat().st_size if path.exists() else 0
        while time.monotonic() < end:
            with open(path) as f:
                f.seek(start)
                if text in f.read():
                    return
            time.sleep(0.1)
        # not fatal: a refused service keeps retrying; the experiment records what happens

    def stop(self, which: str, kill: bool = False) -> None:
        p = self.procs.pop(which, None)
        if not p:
            return
        p.send_signal(                              # (broker: start.sh exec's mosquitto, so p.pid is mosquitto)
signal.SIGKILL if kill else signal.SIGTERM)
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()

    def pid(self, which: str) -> int | None:
        p = self.procs.get(which)
        return p.pid if p else None

    def up(self) -> "Stack":
        self.start("broker", fresh=True)
        self.start("gateway")
        self.start("historian")
        return self

    def down(self) -> None:
        for which in ("historian", "gateway", "broker"):
            self.stop(which)


def database(action: str) -> None:
    """Stop or start the PostgreSQL server (E4)."""
    subprocess.run(PG_CTL.format(action), shell=True, check=True, capture_output=True)
    if action == "start":
        for _ in range(50):
            try:
                psycopg.connect(DB_URL, connect_timeout=1).close()
                return
            except psycopg.OperationalError:
                time.sleep(0.2)


def sql(query: str, params=None) -> list[tuple]:
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else []


def clear_tables() -> None:
    sql("TRUNCATE readings, quarantine, series RESTART IDENTITY CASCADE")


# --- A device -------------------------------------------------------------------------------
@dataclass
class Sent:
    ts: int                 # sensor time put in the message (epoch ms), unique per message
    wall: float             # time.time() when publish() was called
    rc: int                 # publish() return code


class Device:
    """Publishes Acme messages like testing/vendors/acme_publisher.py does (paho defaults: MQTT 3.1.1,
    clean session, QoS 1). max_inflight raised so the generator itself isn't the bottleneck in E3."""

    def __init__(self, port: int = PORT, user: str = "acme_hvac_0001", inflight: int = 1000):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=user)
        self.client.username_pw_set(user, PASSWORDS[user])
        self.client.max_inflight_messages_set(inflight)
        self.client.max_queued_messages_set(0)          # 0 = unlimited (paho default)
        self.connected = threading.Event()
        self.client.on_connect = lambda c, u, f, rc, p: self.connected.set() if not rc.is_failure else None
        self.client.on_disconnect = lambda c, u, f, rc, p: self.connected.clear()
        self.acked: list[float] = []                    # when each PUBACK came back (broker has it)
        self.client.on_publish = lambda c, u, mid, rc, p: self.acked.append(time.time())
        self.client.connect_async("127.0.0.1", port)
        self.client.loop_start()
        self.connected.wait(10)
        self.sent: list[Sent] = []

    def send(self, ts: int, temp_f: float = 70.0, mode: int = 2, extra: dict | None = None, raw: bytes | None = None,
             topic: str = TOPIC) -> None:
        payload = raw if raw is not None else json.dumps(
            {"deviceId": "ACME-HVAC-0001", "ts": ts, "tempF": temp_f, "rh": 50.0, "op_state": mode, **(extra or {})})
        info = self.client.publish(topic, payload, qos=1)
        self.sent.append(Sent(ts, time.time(), info.rc))

    def run(self, rate: float, seconds: float, ts0: int) -> None:
        """Send `rate` messages a second for `seconds`; sensor times ts0, ts0+1 ms, ... (unique)."""
        n, start = int(rate * seconds), time.perf_counter()
        for i in range(n):
            target = start + i / rate
            delay = target - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            self.send(ts0 + i, temp_f=68.0 + (i % 50) / 10)

    def wait_published(self, timeout: float = 120) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not self.client._out_messages:           # paho's own queue of unacknowledged messages
                return True
            time.sleep(0.05)
        return False

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


# --- Results ----------------------------------------------------------------------------------
def stored(ts0: int, ts1: int, point: str = TEMP_POINT) -> list[tuple]:
    """(sensor_time ms, commit time epoch s, quality) for the point's readings in [ts0, ts1]."""
    return sql("""
        SELECT (extract(epoch FROM r.sensor_time) * 1000)::bigint,
               extract(epoch FROM pg_xact_commit_timestamp(r.xmin))::float8, r.quality
        FROM readings r JOIN series s USING (series_id)
        WHERE s.point_id = %s AND r.sensor_time BETWEEN to_timestamp(%s / 1000.0) AND to_timestamp(%s / 1000.0)
        ORDER BY 1""", (point, ts0, ts1))


def wait_stored(expected: int, ts0: int, ts1: int, timeout: float = 120, settle: float = 3) -> list[tuple]:
    """Poll until `expected` rows are stored or nothing new arrives for `settle` s after timeout."""
    end, last, last_change = time.monotonic() + timeout, -1, time.monotonic()
    while True:
        n = sql("""SELECT count(*) FROM readings r JOIN series s USING (series_id) WHERE s.point_id = %s
                   AND r.sensor_time BETWEEN to_timestamp(%s / 1000.0) AND to_timestamp(%s / 1000.0)""",
                (TEMP_POINT, ts0, ts1))[0][0]
        if n != last:
            last, last_change = n, time.monotonic()
        if n >= expected or (time.monotonic() > end and time.monotonic() - last_change > settle):
            break
        time.sleep(0.25)
    return stored(ts0, ts1)


class Sampler:
    """CPU % and memory of named processes, sampled every second in the background."""

    def __init__(self, pids: dict[str, int]):
        self.procs = {k: psutil.Process(v) for k, v in pids.items() if v}
        self.rows: list[dict] = []
        self._stop = threading.Event()
        for p in self.procs.values():
            p.cpu_percent(None)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self._stop.wait(1):
            row = {"t": time.time()}
            for k, p in self.procs.items():
                try:
                    row[f"{k}_cpu"] = p.cpu_percent(None)
                    row[f"{k}_mb"] = p.memory_info().rss / 1e6
                except psutil.Error:
                    pass
            self.rows.append(row)

    def stop(self) -> list[dict]:
        self._stop.set()
        self.thread.join()
        return self.rows


def postgres_pids() -> list[int]:
    return [p.pid for p in psutil.process_iter(["name", "username"]) if p.info["name"] == "postgres"]


def write_csv(name: str, rows: list[dict]) -> Path:
    import csv
    path = RESULTS / name
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    return path


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

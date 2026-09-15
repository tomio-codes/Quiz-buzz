#!/usr/bin/env python3
"""Moderátorský server pro quiz-buzz: čte přijímač a servíruje obrazovku na projektor."""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import serial
import serial.tools.list_ports

ROOT = Path(__file__).resolve().parent
TEAMS = json.loads((ROOT / "teams.json").read_text(encoding="utf-8"))
STATIC = ROOT / "static"
DEMO = False

def initial_scores() -> dict[str, int]:
    return {team_id: 0 for team_id in TEAMS}


state_lock = threading.Lock()
state = {"status": "idle", "team": None, "scores": initial_scores()}
subscribers: list[queue.Queue] = []
subscribers_lock = threading.Lock()
serial_lock = threading.Lock()
serial_port = None
CDC_SETTLE_S = 2.0
REOPEN_WAIT_S = 1.0
online_teams: set[int] = set()
last_seen_teams: dict[int, float] = {}
warned_teams: set[int] = set()
paused_teams: set[int] = set()
TEAM_WARN_S = 3.0
TEAM_PAUSE_S = 5.0


def team_name(team_id: int) -> str:
    return TEAMS[str(team_id)]["name"]


def publish() -> None:
    payload = json.dumps(state_snapshot(), ensure_ascii=False)
    with subscribers_lock:
        for subscriber in subscribers:
            subscriber.put(payload)


def serial_command(command: str) -> None:
    for attempt in range(2):
        try:
            with serial_lock:
                if serial_port is not None and serial_port.is_open:
                    serial_port.write(f"{command}\n".encode("ascii"))
            return
        except serial.SerialException:
            if attempt == 0:
                reopen_receiver()
            else:
                return


def read_serial_chunk() -> bytes:
    try:
        with serial_lock:
            return serial_port.read(256)
    except serial.SerialException:
        reopen_receiver()
        return b""


def unlock_receiver() -> None:
    serial_command("RESET")


def set_idle() -> None:
    with state_lock:
        if state["status"] == "finished":
            return
        if state["status"] == "paused":
            unlock_receiver()
            return
        state["status"] = "idle"
        state["team"] = None
    unlock_receiver()
    publish()


def set_buzz(team_id: int) -> None:
    if str(team_id) not in TEAMS:
        raise ValueError(f"Neznámé číslo týmu: {team_id}")
    with state_lock:
        if state["status"] == "paused":
            return
        if state["status"] != "idle":
            return
        state["status"] = "locked"
        state["team"] = team_id
    publish()


def award_points(points: int) -> None:
    if points not in (1, 2, 3):
        raise ValueError(f"Neplatné body: {points}")
    with state_lock:
        if state["status"] == "paused":
            raise ValueError("Hra je pozastavena")
        if state["status"] != "locked":
            raise ValueError("Bodovat lze jen po přihlášení")
        state["scores"][str(state["team"])] += points
        state["status"] = "idle"
        state["team"] = None
    unlock_receiver()
    publish()


def finish_game() -> None:
    with state_lock:
        state["status"] = "finished"
        state["team"] = None
    unlock_receiver()
    publish()


def new_game() -> None:
    with state_lock:
        state["status"] = "idle"
        state["team"] = None
        state["scores"] = initial_scores()
    unlock_receiver()
    publish()


def find_port() -> str:
    ports = list(serial.tools.list_ports.comports())
    if len(ports) == 0:
        raise SystemExit("Nenalezen žádný sériový port. Připojte přijímač USB.")
    if len(ports) == 1:
        return ports[0].device
    print("Více sériových portů:")
    for port in ports:
        print(f"  {port.device}\t{port.description}", flush=True)
    raise SystemExit("Spusťte znovu s --port COMx")


def serial_winerror(error: BaseException) -> int:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, OSError) and current.winerror is not None:
            return current.winerror
        current = current.__cause__
    return 0


def open_serial(port_name: str) -> serial.Serial:
    port = serial.Serial()
    port.port = port_name
    port.baudrate = 115200
    port.timeout = 0.2
    port.dsrdtr = False
    port.rtscts = False
    port.dtr = False
    port.rts = False
    port.open()
    time.sleep(CDC_SETTLE_S)
    return port


def open_receiver(port_name: str) -> serial.Serial:
    while True:
        try:
            port = open_serial(port_name)
            print(f"Nalezeno připojení s přijímačem na {port_name}", flush=True)
            return port
        except serial.SerialException as error:
            if serial_winerror(error) == 5:
                raise SystemExit(
                    f"Nelze otevřít {port_name}: přístup odepřen. "
                    "Port používá jiný program — zavřete Serial Monitor v Arduino IDE "
                    "a druhou kopii server.py, pak spusťte znovu."
                )
            print("Přijímač se po otevření portu resetuje, čekám...", flush=True)
            time.sleep(REOPEN_WAIT_S)


def reopen_receiver() -> None:
    global serial_port
    port_name = serial_port.port
    print("Spojení s přijímačem se přerušilo, připojuji znovu...", flush=True)
    with serial_lock:
        try:
            serial_port.close()
        except serial.SerialException:
            pass
        while True:
            try:
                serial_port = open_serial(port_name)
                break
            except serial.SerialException:
                time.sleep(REOPEN_WAIT_S)
    print(f"Nalezeno připojení s přijímačem na {port_name}", flush=True)


def enter_pause() -> None:
    with state_lock:
        if state["status"] == "finished":
            return
        if state["status"] == "locked":
            state["team"] = None
        state["status"] = "paused"
    unlock_receiver()
    publish()


def try_resume() -> None:
    with state_lock:
        if state["status"] != "paused":
            return
        if paused_teams:
            return
        state["status"] = "idle"
        state["team"] = None
    publish()


def mark_team_contact(team_id: int) -> None:
    last_seen_teams[team_id] = time.monotonic()
    warned_teams.discard(team_id)
    was_paused = team_id in paused_teams
    if was_paused:
        paused_teams.discard(team_id)
        print(f"Obnoveno spojení s tlačítkem {team_name(team_id)}", flush=True)
    if team_id not in online_teams:
        online_teams.add(team_id)
        print(f"Nalezeno připojení s modulem {team_name(team_id)}", flush=True)
    if not paused_teams:
        try_resume()


def check_team_timeouts() -> None:
    now = time.monotonic()
    newly_paused = False
    for team_id in list(online_teams):
        age = now - last_seen_teams.get(team_id, 0.0)
        if age >= TEAM_WARN_S and team_id not in warned_teams:
            warned_teams.add(team_id)
            print(f"Ztráta spojení s tlačítkem {team_name(team_id)}", flush=True)
        if age >= TEAM_PAUSE_S and team_id not in paused_teams:
            paused_teams.add(team_id)
            newly_paused = True
            print(
                f"Tlačítko {team_name(team_id)} nekomunikuje — hra pozastavena",
                flush=True,
            )
    if newly_paused:
        enter_pause()


def parse_serial_lines(buffer: str) -> tuple[str, list[str]]:
    lines: list[str] = []
    while "\n" in buffer:
        line, buffer = buffer.split("\n", 1)
        lines.append(line.strip())
    return buffer, lines


def handle_serial_line(line: str) -> None:
    parts = line.split()
    if not parts:
        return
    command = parts[0]
    if command in ("ALIVE", "LINK", "BUZZ") and len(parts) == 2:
        team_id = int(parts[1])
        mark_team_contact(team_id)
        if command == "BUZZ":
            set_buzz(team_id)
        return
    if command == "RESET":
        set_idle()
        return
    if command == "ERROR":
        print(line, flush=True)


def serial_loop() -> None:
    buffer = ""
    while True:
        chunk = read_serial_chunk()
        if chunk:
            buffer += chunk.decode("ascii", errors="replace")
            buffer, lines = parse_serial_lines(buffer)
            for line in lines:
                handle_serial_line(line)
        check_team_timeouts()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def handle(self):
        try:
            super().handle()
        except ConnectionError:
            return

    def finish(self):
        try:
            super().finish()
        except ConnectionError:
            return

    def log_message(self, format, *args):
        return

    def do_GET(self):
        if self.path == "/api/state":
            self._json(state_snapshot())
            return
        if self.path == "/api/teams":
            self._json(TEAMS)
            return
        if self.path == "/api/config":
            self._json({"demo": DEMO})
            return
        if self.path == "/api/events":
            self._sse()
            return
        super().do_GET()

    def do_POST(self):
        if self.path == "/api/reset":
            set_idle()
            self._json({"ok": True})
            return
        if self.path == "/api/award":
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            try:
                award_points(int(body["points"]))
            except ValueError:
                self.send_error(HTTPStatus.CONFLICT)
                return
            self._json({"ok": True})
            return
        if self.path == "/api/finish":
            finish_game()
            self._json({"ok": True})
            return
        if self.path == "/api/new-game":
            new_game()
            self._json({"ok": True})
            return
        if self.path == "/api/demo-buzz":
            if not DEMO:
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            set_buzz(int(body["team"]))
            self._json({"ok": True})
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _json(self, payload: object) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _sse(self) -> None:
        subscriber: queue.Queue = queue.Queue()
        with subscribers_lock:
            subscribers.append(subscriber)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        subscriber.put(json.dumps(state_snapshot(), ensure_ascii=False))
        try:
            while True:
                payload = subscriber.get()
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
        except ConnectionError:
            return
        finally:
            with subscribers_lock:
                subscribers.remove(subscriber)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        exc_type = sys.exc_info()[0]
        if exc_type is not None and issubclass(exc_type, ConnectionError):
            return
        super().handle_error(request, client_address)


def state_snapshot() -> dict:
    with state_lock:
        snapshot = {
            "status": state["status"],
            "team": state["team"],
            "scores": dict(state["scores"]),
        }
        if paused_teams:
            snapshot["offline_teams"] = sorted(paused_teams)
        return snapshot


def main() -> None:
    global DEMO, serial_port
    parser = argparse.ArgumentParser(description="Quiz-buzz moderátorská obrazovka")
    parser.add_argument("--port", help="Sériový port přijímače, např. COM5")
    parser.add_argument("--http-port", type=int, default=8080)
    parser.add_argument("--demo", action="store_true", help="Bez hardwaru, klávesy 1/2/3 v prohlížeči")
    args = parser.parse_args()
    DEMO = args.demo

    if not args.demo:
        serial_port = open_receiver(args.port or find_port())
        thread = threading.Thread(target=serial_loop, daemon=True)
        thread.start()
    else:
        print("Demo režim: v prohlížeči klávesy 1, 2, 3", flush=True)

    server = Server(("127.0.0.1", args.http_port), Handler)
    print(f"Projektor: http://127.0.0.1:{args.http_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        sys.exit(0)


if __name__ == "__main__":
    main()

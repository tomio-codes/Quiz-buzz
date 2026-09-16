#!/usr/bin/env python3
"""Moderátorský server pro quiz-buzz: čte přijímač a servíruje obrazovku na projektor."""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import serial
import serial.tools.list_ports

ROOT = Path(__file__).resolve().parent
ALL_TEAMS = json.loads((ROOT / "teams.json").read_text(encoding="utf-8"))
TEAM_PRESETS: dict[int, list[int]] = {
    2: [1, 3],
    3: [1, 2, 3],
    4: [1, 2, 3, 4],
}
STATIC = ROOT / "static"
DEMO = False
TEAMS: dict[str, dict[str, str]] = {}
ACTIVE_TEAM_IDS: list[int] = []
MIN_ONLINE_TEAMS = 3


def configure_teams(team_count: int) -> None:
    global TEAMS, ACTIVE_TEAM_IDS, MIN_ONLINE_TEAMS
    if team_count not in TEAM_PRESETS:
        raise SystemExit(f"Neplatný počet týmů: {team_count} (povoleno 2–4)")
    ACTIVE_TEAM_IDS = TEAM_PRESETS[team_count]
    TEAMS = {str(team_id): ALL_TEAMS[str(team_id)] for team_id in ACTIVE_TEAM_IDS}
    MIN_ONLINE_TEAMS = team_count
    reset_team_links()
    with state_lock:
        state["scores"] = initial_scores()


def initial_scores() -> dict[str, int]:
    return {team_id: 0 for team_id in TEAMS}


def active_team(team_id: int) -> bool:
    return team_id in ACTIVE_TEAM_IDS


state_lock = threading.Lock()
state = {"status": "waiting", "team": None, "scores": {}}
subscribers: list[queue.Queue] = []
subscribers_lock = threading.Lock()
serial_lock = threading.Lock()
serial_port = None
CDC_SETTLE_S = 2.0
REOPEN_WAIT_S = 1.0
HELLO_INTERVAL_S = 1.0
LINK_WARN_S = HELLO_INTERVAL_S * 3
LINK_DEAD_S = HELLO_INTERVAL_S * 5


@dataclass
class TeamLink:
    last_alive: float = 0.0
    last_seq: int = -1
    seen: bool = False


team_links: dict[int, TeamLink] = {}
link_bitmap_cache: tuple[bool, ...] = ()


def reset_team_links() -> None:
    global team_links, link_bitmap_cache
    team_links = {team_id: TeamLink() for team_id in ACTIVE_TEAM_IDS}
    link_bitmap_cache = ()


def link_age(team_id: int) -> float:
    link = team_links[team_id]
    if not link.seen:
        return float("inf")
    return time.monotonic() - link.last_alive


def team_connected(team_id: int) -> bool:
    if DEMO:
        return True
    link = team_links[team_id]
    return link.seen and link_age(team_id) < LINK_WARN_S


def team_alive(team_id: int) -> bool:
    if DEMO:
        return True
    link = team_links[team_id]
    return link.seen and link_age(team_id) < LINK_DEAD_S


def online_active_count() -> int:
    return sum(1 for team_id in ACTIVE_TEAM_IDS if team_alive(team_id))


def connected_teams_list() -> list[int]:
    return [team_id for team_id in ACTIVE_TEAM_IDS if team_connected(team_id)]


def all_teams_alive() -> bool:
    return all(team_alive(team_id) for team_id in ACTIVE_TEAM_IDS)


def all_teams_seen() -> bool:
    return all(team_links[team_id].seen for team_id in ACTIVE_TEAM_IDS)


def offline_teams_list() -> list[int]:
    return [team_id for team_id in ACTIVE_TEAM_IDS if team_links[team_id].seen and not team_alive(team_id)]


def team_name(team_id: int) -> str:
    return TEAMS[str(team_id)]["name"]


def log(message: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


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


def sync_receiver_unlock() -> None:
    """Uvolní přijímač, pokud server buzz nepřijímá — jinak zůstane HW uzamčený."""
    unlock_receiver()


def resume_status() -> str:
    if all_teams_alive() and all_teams_seen():
        return "idle"
    if any(team_links[team_id].seen for team_id in ACTIVE_TEAM_IDS):
        return "paused"
    return "idle"


def receive_alive(team_id: int, seq: int | None) -> None:
    if not active_team(team_id):
        return
    link = team_links[team_id]
    first = not link.seen
    if seq is not None and seq > link.last_seq:
        link.last_seq = seq
    link.last_alive = time.monotonic()
    link.seen = True
    if first:
        log(f"Připojeno tlačítko {team_name(team_id)}")
    evaluate_game_links()


def touch_team(team_id: int) -> None:
    if not active_team(team_id):
        return
    link = team_links[team_id]
    first = not link.seen
    link.last_alive = time.monotonic()
    link.seen = True
    if first:
        log(f"Připojeno tlačítko {team_name(team_id)}")
    evaluate_game_links()


def evaluate_game_links() -> None:
    global link_bitmap_cache
    bitmap = tuple(team_connected(team_id) for team_id in ACTIVE_TEAM_IDS)
    alive_now = all_teams_alive()
    seen_now = all_teams_seen()
    need_unlock = False
    status_changed = False

    with state_lock:
        status = state["status"]
        if status == "finished":
            pass
        elif status == "waiting":
            if seen_now and alive_now:
                state["status"] = "idle"
                names = ", ".join(team_name(team_id) for team_id in ACTIVE_TEAM_IDS)
                log(f"Připojena všechna tlačítka ({names}) — hra může začít")
                status_changed = True
        elif status == "paused":
            if alive_now:
                state["status"] = "idle"
                state["team"] = None
                log("Obnovena spojení — hra pokračuje")
                status_changed = True
                need_unlock = True
        elif status in ("idle", "locked") and seen_now and not alive_now:
            dead = [team_name(team_id) for team_id in ACTIVE_TEAM_IDS if not team_alive(team_id)]
            if status == "locked":
                state["team"] = None
            state["status"] = "paused"
            log(f"Hra pozastavena — {', '.join(dead)}")
            status_changed = True
            need_unlock = True

    if need_unlock:
        unlock_receiver()
    if status_changed or bitmap != link_bitmap_cache:
        link_bitmap_cache = bitmap
        publish()


def set_idle() -> None:
    with state_lock:
        if state["status"] == "finished":
            return
        state["team"] = None
        state["status"] = resume_status()
    sync_receiver_unlock()
    publish()


def try_buzz(team_id: int) -> None:
    if not active_team(team_id):
        sync_receiver_unlock()
        return
    accepted = False
    with state_lock:
        status = state["status"]
        if status == "idle":
            state["status"] = "locked"
            state["team"] = team_id
            accepted = True
        elif status == "locked":
            return
        elif status == "paused":
            log(f"Stisk {team_name(team_id)} ignorován — hra je pozastavena, odemykám přijímač")
        elif status == "waiting":
            log(f"Stisk {team_name(team_id)} ignorován — čeká se na tlačítka, odemykám přijímač")
        else:
            log(f"Stisk {team_name(team_id)} ignorován ({status}), odemykám přijímač")
    if accepted:
        publish()
    else:
        sync_receiver_unlock()


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
        state["team"] = None
        state["scores"] = initial_scores()
        if all_teams_seen() and all_teams_alive():
            state["status"] = "idle"
        else:
            state["status"] = "waiting"
    unlock_receiver()
    publish()


def find_port() -> str:
    ports = list(serial.tools.list_ports.comports())
    if len(ports) == 0:
        raise SystemExit("Nenalezen žádný sériový port. Připojte přijímač USB.")
    if len(ports) == 1:
        return ports[0].device
    log("Více sériových portů:")
    for port in ports:
        log(f"  {port.device}\t{port.description}")
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
            log(f"Nalezeno připojení s přijímačem na {port_name}")
            return port
        except serial.SerialException as error:
            if serial_winerror(error) == 5:
                raise SystemExit(
                    f"Nelze otevřít {port_name}: přístup odepřen. "
                    "Port používá jiný program — zavřete Serial Monitor v Arduino IDE "
                    "a druhou kopii server.py, pak spusťte znovu."
                )
            log("Přijímač se po otevření portu resetuje, čekám...")
            time.sleep(REOPEN_WAIT_S)


def reopen_receiver() -> None:
    global serial_port
    port_name = serial_port.port
    log("Spojení s přijímačem se přerušilo, připojuji znovu...")
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
    log(f"Nalezeno připojení s přijímačem na {port_name}")


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
    if command == "ALIVE" and len(parts) in (2, 3):
        team_id = int(parts[1])
        seq = int(parts[2]) if len(parts) == 3 else None
        receive_alive(team_id, seq)
        return
    if command == "BUZZ" and len(parts) == 2:
        team_id = int(parts[1])
        touch_team(team_id)
        try_buzz(team_id)
        return
    if command == "RESET":
        set_idle()
        return
    if command == "ERROR":
        log(line)


def heartbeat_loop() -> None:
    while True:
        evaluate_game_links()
        time.sleep(0.25)


def serial_loop() -> None:
    buffer = ""
    while True:
        chunk = read_serial_chunk()
        if chunk:
            buffer += chunk.decode("ascii", errors="replace")
            buffer, lines = parse_serial_lines(buffer)
            for line in lines:
                try:
                    handle_serial_line(line)
                except Exception as error:
                    log(f"Chyba zpracování '{line}': {error}")


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
            try_buzz(int(body["team"]))
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
            "online_count": online_active_count(),
            "min_teams": MIN_ONLINE_TEAMS,
            "connected_teams": connected_teams_list(),
        }
        offline = offline_teams_list()
        if offline:
            snapshot["offline_teams"] = offline
        return snapshot


def main() -> None:
    global DEMO, serial_port
    parser = argparse.ArgumentParser(description="Quiz-buzz moderátorská obrazovka")
    parser.add_argument("--port", help="Sériový port přijímače, např. COM5")
    parser.add_argument("--http-port", type=int, default=8080)
    parser.add_argument(
        "--teams",
        type=int,
        choices=[2, 3, 4],
        default=3,
        help="Počet tlačítek: 2=červený+modrý, 3=+zelený, 4=+žlutý",
    )
    parser.add_argument("--demo", action="store_true", help="Bez hardwaru, klávesy podle čísel týmů")
    args = parser.parse_args()
    DEMO = args.demo
    configure_teams(args.teams)
    team_keys = ", ".join(str(team_id) for team_id in ACTIVE_TEAM_IDS)

    if not args.demo:
        names = ", ".join(team_name(team_id) for team_id in ACTIVE_TEAM_IDS)
        log(f"Čeká se na {MIN_ONLINE_TEAMS} tlačítka: {names}")
        serial_port = open_receiver(args.port or find_port())
        threading.Thread(target=serial_loop, daemon=True).start()
        threading.Thread(target=heartbeat_loop, daemon=True).start()
    else:
        with state_lock:
            state["status"] = "idle"
        log(f"Demo režim: v prohlížeči klávesy {team_keys}")

    server = Server(("127.0.0.1", args.http_port), Handler)
    log(f"Projektor: http://127.0.0.1:{args.http_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        sys.exit(0)


if __name__ == "__main__":
    main()

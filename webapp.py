from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from assistant import (
    DB_PATH,
    handle_ask,
    init_db,
    parse_days_left_query,
    remove_event,
    send_notification,
)


APP_DIR = Path(__file__).parent
WEB_DIR = APP_DIR / "web"

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="/static")


class NotifierState:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.poll_seconds = 15

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            return True

    def stop(self) -> bool:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                return False
            self._stop.set()
            return True

    def _run(self) -> None:
        while not self._stop.is_set():
            now = datetime.now()
            window_start = now - timedelta(seconds=self.poll_seconds)
            conn = sqlite3.connect(DB_PATH)
            try:
                rows = conn.execute(
                    """
                    SELECT id, title, event_time
                    FROM events
                    WHERE notified = 0
                    """
                ).fetchall()
                for event_id, title, event_time in rows:
                    event_dt = datetime.fromisoformat(event_time)
                    if window_start <= event_dt <= now:
                        send_notification("Schedule Alert", f"{title} ({event_dt:%m-%d %H:%M})")
                        conn.execute("UPDATE events SET notified = 1 WHERE id = ?", (event_id,))
                conn.commit()
            finally:
                conn.close()
            self._stop.wait(self.poll_seconds)


notifier = NotifierState()


def dday_label(target: datetime, today: datetime | None = None) -> str:
    today = today or datetime.now()
    diff = (target.date() - today.date()).days
    if diff > 0:
        return f"D-{diff}"
    if diff == 0:
        return "D-Day"
    return f"D+{abs(diff)}"


def get_events() -> list[dict[str, object]]:
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT id, title, event_time, notified FROM events ORDER BY event_time ASC"
        ).fetchall()
    finally:
        conn.close()

    out: list[dict[str, object]] = []
    for event_id, title, event_time, notified in rows:
        dt = datetime.fromisoformat(event_time)
        out.append(
            {
                "id": event_id,
                "title": title,
                "time": dt.isoformat(),
                "time_display": dt.strftime("%Y-%m-%d %H:%M"),
                "date": dt.strftime("%Y-%m-%d"),
                "clock": dt.strftime("%H:%M"),
                "state": "notified" if notified else "pending",
                "dday": dday_label(dt),
            }
        )
    return out


@app.get("/")
def root():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/api/events")
def api_events():
    return jsonify({"events": get_events()})


@app.post("/api/ask")
def api_ask():
    data = request.get_json(silent=True) or {}
    text = str(data.get("text", "")).strip()
    if not text:
        return jsonify({"error": "text is required"}), 400

    days_left = parse_days_left_query(text)
    if days_left is not None:
        return jsonify({"type": "days_left", "message": days_left, "events": []})

    kind, events = handle_ask(text, db_path=DB_PATH)
    if not events:
        return jsonify({"error": "could not parse request"}), 400

    payload = [
        {"title": ev.title, "time": ev.when.isoformat(), "time_display": ev.when.strftime("%Y-%m-%d %H:%M")}
        for ev in events
    ]
    return jsonify({"type": kind, "events": payload})


@app.put("/api/events/<int:event_id>")
def api_edit_event(event_id: int):
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    date_text = str(data.get("date", "")).strip()
    time_text = str(data.get("clock", "")).strip()

    if not title:
        return jsonify({"error": "title is required"}), 400
    try:
        dt = datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M")
    except ValueError:
        return jsonify({"error": "invalid date/time format"}), 400

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            "UPDATE events SET title = ?, event_time = ?, notified = 0 WHERE id = ?",
            (title, dt.isoformat(), event_id),
        )
        conn.commit()
    finally:
        conn.close()

    if cur.rowcount <= 0:
        return jsonify({"error": "event not found"}), 404
    return jsonify({"ok": True})


@app.delete("/api/events/<int:event_id>")
def api_delete_event(event_id: int):
    ok = remove_event(event_id, db_path=DB_PATH)
    if not ok:
        return jsonify({"error": "event not found"}), 404
    return jsonify({"ok": True})


@app.get("/api/notifier/status")
def api_notifier_status():
    return jsonify({"running": notifier.is_running()})


@app.post("/api/notifier/start")
def api_notifier_start():
    started = notifier.start()
    return jsonify({"running": True, "started": started})


@app.post("/api/notifier/stop")
def api_notifier_stop():
    stopped = notifier.stop()
    return jsonify({"running": False, "stopped": stopped})


def main() -> None:
    init_db(DB_PATH)
    app.run(host="127.0.0.1", port=5842, debug=False)


if __name__ == "__main__":
    main()

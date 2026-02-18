from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

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
ASSETS_DIR = APP_DIR / "assets"
USER_ILLUST_PATH = ASSETS_DIR / "user_illustration.png"
WEB_SETTINGS_PATH = APP_DIR / "web_settings.json"

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


def load_web_settings() -> dict[str, int]:
    defaults = {
        "scale": 100,
        "offset_x": 0,
        "offset_y": 0,
        "width": 260,
        "height": 96,
    }
    if not WEB_SETTINGS_PATH.exists():
        return defaults
    try:
        data = json.loads(WEB_SETTINGS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return defaults
        for k in defaults:
            if k in data:
                defaults[k] = int(data[k])
        return defaults
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return defaults


def save_web_settings(data: dict[str, int]) -> None:
    WEB_SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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


@app.get("/api/illustration/settings")
def api_illustration_settings_get():
    return jsonify(load_web_settings())


@app.put("/api/illustration/settings")
def api_illustration_settings_put():
    body = request.get_json(silent=True) or {}
    current = load_web_settings()
    for key in ("scale", "offset_x", "offset_y", "width", "height"):
        if key in body:
            try:
                current[key] = int(body[key])
            except (ValueError, TypeError):
                return jsonify({"error": f"invalid {key}"}), 400

    current["scale"] = max(40, min(220, current["scale"]))
    current["offset_x"] = max(-200, min(200, current["offset_x"]))
    current["offset_y"] = max(-160, min(160, current["offset_y"]))
    current["width"] = max(180, min(520, current["width"]))
    current["height"] = max(80, min(240, current["height"]))
    save_web_settings(current)
    return jsonify({"ok": True, "settings": current})


@app.post("/api/illustration/upload")
def api_illustration_upload():
    if "image" not in request.files:
        return jsonify({"error": "image file is required"}), 400
    file = request.files["image"]
    if not file.filename:
        return jsonify({"error": "image file is required"}), 400
    if not file.filename.lower().endswith(".png"):
        return jsonify({"error": "only PNG is supported"}), 400

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    file.save(USER_ILLUST_PATH)
    return jsonify({"ok": True})


@app.get("/api/illustration/image")
def api_illustration_image():
    if not USER_ILLUST_PATH.exists():
        return jsonify({"error": "image not found"}), 404
    return send_file(USER_ILLUST_PATH, mimetype="image/png")


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

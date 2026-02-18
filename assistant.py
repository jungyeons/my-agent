from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from plyer import notification
except Exception:  # pragma: no cover
    notification = None


DB_PATH = Path("schedule.db")
MEMORY_PATH = Path("chat_memory.json")

# Korean tokens as unicode escapes for stable terminal/file encoding.
K_DAY = "\uC77C"
K_MONTH = "\uC6D4"
K_AM = "\uC624\uC804"
K_PM = "\uC624\uD6C4"
K_HOUR = "\uC2DC"
K_MIN = "\uBD84"
K_HOURS = "\uC2DC\uAC04"
K_STUDY = "\uACF5\uBD80"
K_PLAN = "\uACC4\uD68D"
K_EXAM = "\uC2DC\uD5D8"
K_CODING_TEST = "\uCF54\uB529\uD14C\uC2A4\uD2B8"
K_DEFAULT_TITLE = "\uC77C\uC815"
K_EXIT = "\uC885\uB8CC"
K_HELP = "\uB3C4\uC6C0\uB9D0"
K_DELETE = "\uC0AD\uC81C"
K_SHOW = "\uBCF4\uC5EC"
K_DISTRIBUTE = "\uBC30\uBD84"
K_COUNTDOWN = "\uC5ED\uC0B0"
K_SUBJECT = "\uACFC\uBAA9"
K_UNTIL = "\uAE4C\uC9C0"
K_PER_DAY = "\uD558\uB8E8"
K_HOW_MANY_DAYS = "\uBA70\uCE60"
K_REMAIN = "\uB0A8"
K_DDAY = "d-day"


@dataclass
class ParsedEvent:
    when: datetime
    title: str


@dataclass
class SubjectLoad:
    name: str
    amount: float
    unit: str  # "hours" | "weight"


@dataclass
class ChatMemory:
    exam_date: datetime | None = None
    subjects: list[str] | None = None
    daily_hours: float | None = None
    study_goal: str | None = None
    study_days: int | None = None


def chat_memory_to_dict(memory: ChatMemory) -> dict[str, object]:
    return {
        "exam_date": memory.exam_date.isoformat() if memory.exam_date else None,
        "subjects": memory.subjects or [],
        "daily_hours": memory.daily_hours,
        "study_goal": memory.study_goal,
        "study_days": memory.study_days,
    }


def dict_to_chat_memory(data: dict[str, object]) -> ChatMemory:
    exam_date_raw = data.get("exam_date")
    exam_date = None
    if isinstance(exam_date_raw, str) and exam_date_raw:
        try:
            exam_date = datetime.fromisoformat(exam_date_raw)
        except ValueError:
            exam_date = None

    subjects_raw = data.get("subjects")
    subjects: list[str] | None = None
    if isinstance(subjects_raw, list):
        subjects = [str(x) for x in subjects_raw if str(x).strip()]
        if not subjects:
            subjects = None

    daily_hours_raw = data.get("daily_hours")
    daily_hours = float(daily_hours_raw) if isinstance(daily_hours_raw, (int, float)) else None

    study_goal_raw = data.get("study_goal")
    study_goal = str(study_goal_raw) if isinstance(study_goal_raw, str) and study_goal_raw.strip() else None

    study_days_raw = data.get("study_days")
    study_days = int(study_days_raw) if isinstance(study_days_raw, int) else None

    return ChatMemory(
        exam_date=exam_date,
        subjects=subjects,
        daily_hours=daily_hours,
        study_goal=study_goal,
        study_days=study_days,
    )


def save_chat_memory(memory: ChatMemory, path: Path = MEMORY_PATH) -> bool:
    try:
        path.write_text(json.dumps(chat_memory_to_dict(memory), ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False


def load_chat_memory(path: Path = MEMORY_PATH) -> ChatMemory:
    if not path.exists():
        return ChatMemory()
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return ChatMemory()
        return dict_to_chat_memory(data)
    except (OSError, json.JSONDecodeError):
        return ChatMemory()


def init_db(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                event_time TEXT NOT NULL,
                notified INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def infer_date(base: datetime, day: int) -> datetime:
    year = base.year
    month = base.month
    candidate = datetime(year, month, day)
    if candidate.date() < base.date():
        if month == 12:
            candidate = datetime(year + 1, 1, day)
        else:
            candidate = datetime(year, month + 1, day)
    return candidate


def infer_month_day(base: datetime, month: int, day: int) -> datetime:
    candidate = datetime(base.year, month, day)
    if candidate.date() < base.date():
        candidate = datetime(base.year + 1, month, day)
    return candidate


def normalize_title(raw: str) -> str:
    text = raw.strip(" ,.")
    text = re.sub(
        r"^(\uC5D0\uB294|\uC740|\uB294|\uC774|\uAC00|\uC744|\uB97C|\uC5D0)\s*",
        "",
        text,
    )
    text = re.sub(
        r"(\uC774\uC57C|\uC788\uC5B4|\uC788\uACE0|\uC788\uC2B5\uB2C8\uB2E4|\uC608\uC815)\s*$",
        "",
        text,
    )
    text = text.strip()
    text = re.sub(r"(\uC774|\uAC00|\uC740|\uB294|\uC744|\uB97C)$", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.")
    return text or K_DEFAULT_TITLE


def parse_events_korean(text: str, now: datetime | None = None) -> list[ParsedEvent]:
    now = now or datetime.now()
    results: list[ParsedEvent] = []

    day_re = re.compile(rf"(?P<day>\d{{1,2}})\s*{K_DAY}")
    time_re = re.compile(
        rf"(?:(?P<ampm>{K_AM}|{K_PM})\s*)?(?P<hour>\d{{1,2}})\s*{K_HOUR}(?:\s*(?P<minute>\d{{1,2}})\s*{K_MIN})?"
    )

    cleaned_text = text.replace("\n", " ").strip()
    day_matches = list(day_re.finditer(cleaned_text))

    for idx, day_match in enumerate(day_matches):
        day = int(day_match.group("day"))
        seg_start = day_match.end()
        seg_end = day_matches[idx + 1].start() if idx + 1 < len(day_matches) else len(cleaned_text)
        segment = cleaned_text[seg_start:seg_end].strip(" ,.")
        base_day = infer_date(now, day)

        time_matches = list(time_re.finditer(segment))
        if not time_matches:
            when = base_day.replace(hour=9, minute=0, second=0, microsecond=0)
            results.append(ParsedEvent(when=when, title=normalize_title(segment)))
            continue

        prev_hour_24: int | None = None
        for t_idx, t_match in enumerate(time_matches):
            ampm = t_match.group("ampm")
            hour = int(t_match.group("hour"))
            minute = int(t_match.group("minute") or 0)

            if ampm == K_PM and hour < 12:
                hour += 12
            if ampm == K_AM and hour == 12:
                hour = 0
            if ampm is None and prev_hour_24 is not None and hour <= prev_hour_24 and hour < 12:
                # Heuristic: after "9시", ambiguous "1시" in same segment is likely 13:00.
                hour += 12
            prev_hour_24 = hour

            title_start = t_match.end()
            title_end = time_matches[t_idx + 1].start() if t_idx + 1 < len(time_matches) else len(segment)
            title = normalize_title(segment[title_start:title_end])
            when = base_day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            results.append(ParsedEvent(when=when, title=title))

    return results


def insert_events(events: list[ParsedEvent], db_path: Path = DB_PATH) -> list[ParsedEvent]:
    if not events:
        return []
    conn = sqlite3.connect(db_path)
    try:
        for ev in events:
            day_key = ev.when.strftime("%Y-%m-%d")
            rows = conn.execute(
                """
                SELECT id, title
                FROM events
                WHERE substr(event_time, 1, 10) = ?
                ORDER BY id ASC
                """,
                (day_key,),
            ).fetchall()

            def title_key(text: str) -> str:
                # Normalize for "same schedule" matching regardless of spacing/punctuation.
                key = text.strip().lower()
                key = re.sub(r"[\s\-\_\.\,\!\?\'\"\(\)\[\]\{\}]+", "", key)
                return key

            matching_ids = [row_id for row_id, title in rows if title_key(title) == title_key(ev.title)]

            if matching_ids:
                primary_id = matching_ids[0]
                conn.execute(
                    "UPDATE events SET title = ?, event_time = ?, notified = 0 WHERE id = ?",
                    (ev.title, ev.when.isoformat(), primary_id),
                )
                for duplicate_id in matching_ids[1:]:
                    conn.execute("DELETE FROM events WHERE id = ?", (duplicate_id,))
            else:
                conn.execute(
                    "INSERT INTO events (title, event_time, notified) VALUES (?, ?, 0)",
                    (ev.title, ev.when.isoformat()),
                )
        conn.commit()
    finally:
        conn.close()
    return events


def add_events_from_text(text: str, db_path: Path = DB_PATH) -> list[ParsedEvent]:
    return insert_events(parse_events_korean(text), db_path=db_path)


def create_date_only_event(text: str, now: datetime | None = None) -> ParsedEvent | None:
    now = now or datetime.now()
    target = parse_generic_date(text, now)
    if target is None:
        return None

    cleaned = text
    cleaned = re.sub(r"\d{4}[-\.\/]\d{1,2}[-\.\/]\d{1,2}", "", cleaned)
    cleaned = re.sub(rf"\d{{1,2}}\s*{K_MONTH}\s*\d{{1,2}}\s*{K_DAY}", "", cleaned)
    cleaned = re.sub(rf"\d{{1,2}}\s*{K_DAY}", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.")
    title = normalize_title(cleaned) if cleaned else K_DEFAULT_TITLE

    when = target.replace(hour=9, minute=0, second=0, microsecond=0)
    return ParsedEvent(when=when, title=title)


def create_events_with_explicit_month_date(text: str, now: datetime | None = None) -> list[ParsedEvent]:
    now = now or datetime.now()
    base = parse_generic_date(text, now)
    if base is None:
        return []

    time_re = re.compile(
        rf"(?:(?P<ampm>{K_AM}|{K_PM})\s*)?(?P<hour>\d{{1,2}})\s*{K_HOUR}(?:\s*(?P<minute>\d{{1,2}})\s*{K_MIN})?"
    )

    body = text
    body = re.sub(r"\d{4}[-\.\/]\d{1,2}[-\.\/]\d{1,2}", "", body)
    body = re.sub(rf"\d{{1,2}}\s*{K_MONTH}\s*\d{{1,2}}\s*{K_DAY}", "", body)
    body = body.strip(" ,.")

    matches = list(time_re.finditer(body))
    events: list[ParsedEvent] = []

    if not matches:
        title = normalize_title(body) if body else K_DEFAULT_TITLE
        when = base.replace(hour=9, minute=0, second=0, microsecond=0)
        return [ParsedEvent(when=when, title=title)]

    for idx, m in enumerate(matches):
        ampm = m.group("ampm")
        hour = int(m.group("hour"))
        minute = int(m.group("minute") or 0)
        if ampm == K_PM and hour < 12:
            hour += 12
        if ampm == K_AM and hour == 12:
            hour = 0

        title_start = m.end()
        title_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        title = normalize_title(body[title_start:title_end])
        when = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        events.append(ParsedEvent(when=when, title=title))

    return events


def extract_study_goal(text: str) -> str:
    match = re.search(rf"([^\s,\.]+(?:\s+[^\s,\.]+)?)\s*{K_STUDY}", text)
    if match:
        goal = match.group(1).strip()
        if goal:
            return goal
    return "General"


def create_study_plan_events(
    goal: str,
    days: int,
    daily_hours: float,
    now: datetime | None = None,
) -> list[ParsedEvent]:
    now = now or datetime.now()
    events: list[ParsedEvent] = []
    start_date = now.date() + timedelta(days=1)

    for i in range(days):
        day_date = start_date + timedelta(days=i)
        when = datetime(day_date.year, day_date.month, day_date.day, 20, 0, 0, 0)

        if i < int(days * 0.6):
            phase = "Concepts"
        elif i < int(days * 0.85):
            phase = "Practice"
        else:
            phase = "Review"

        title = f"Study {goal} - {phase} ({daily_hours:g}h)"
        events.append(ParsedEvent(when=when, title=title))
    return events


def make_study_plan_from_text(text: str, now: datetime | None = None) -> list[ParsedEvent]:
    now = now or datetime.now()
    goal = extract_study_goal(text)

    day_match = re.search(rf"(?P<days>\d{{1,3}})\s*{K_DAY}", text)
    hour_match = re.search(rf"(?P<hours>\d{{1,2}}(?:\.\d+)?)\s*{K_HOURS}", text)

    days = int(day_match.group("days")) if day_match else 7
    daily_hours = float(hour_match.group("hours")) if hour_match else 2.0

    if days < 1:
        days = 1
    if days > 180:
        days = 180
    if daily_hours <= 0:
        daily_hours = 1.0

    return create_study_plan_events(goal=goal, days=days, daily_hours=daily_hours, now=now)


def parse_exam_date(text: str, now: datetime) -> datetime | None:
    iso_match = re.search(r"(?P<y>\d{4})[-\.\/](?P<m>\d{1,2})[-\.\/](?P<d>\d{1,2})", text)
    if iso_match:
        return datetime(int(iso_match.group("y")), int(iso_match.group("m")), int(iso_match.group("d")))

    md_match = re.search(rf"(?P<m>\d{{1,2}})\s*{K_MONTH}\s*(?P<d>\d{{1,2}})\s*{K_DAY}", text)
    if md_match:
        return infer_month_day(now, int(md_match.group("m")), int(md_match.group("d")))

    # Fallback: first day mention in exam sentence.
    d_match = re.search(rf"(?P<d>\d{{1,2}})\s*{K_DAY}", text)
    if d_match and (K_EXAM in text or K_CODING_TEST in text):
        return infer_date(now, int(d_match.group("d")))
    return None


def parse_generic_date(text: str, now: datetime) -> datetime | None:
    iso_match = re.search(r"(?P<y>\d{4})[-\.\/](?P<m>\d{1,2})[-\.\/](?P<d>\d{1,2})", text)
    if iso_match:
        return datetime(int(iso_match.group("y")), int(iso_match.group("m")), int(iso_match.group("d")))

    md_match = re.search(rf"(?P<m>\d{{1,2}})\s*{K_MONTH}\s*(?P<d>\d{{1,2}})\s*{K_DAY}", text)
    if md_match:
        return infer_month_day(now, int(md_match.group("m")), int(md_match.group("d")))

    d_match = re.search(rf"(?P<d>\d{{1,2}})\s*{K_DAY}", text)
    if d_match:
        return infer_date(now, int(d_match.group("d")))
    return None


def parse_days_left_query(text: str, now: datetime | None = None) -> str | None:
    now = now or datetime.now()
    lowered = text.lower().strip()
    looks_like_query = (K_HOW_MANY_DAYS in text) or (K_REMAIN in text) or (K_DDAY in lowered)
    if not looks_like_query:
        return None

    target = parse_generic_date(text, now)
    if target is None:
        return None

    days = (target.date() - now.date()).days
    if days > 0:
        return f"{target:%Y-%m-%d}까지 {days}일 남았어요. (D-{days})"
    if days == 0:
        return f"{target:%Y-%m-%d} 오늘입니다. (D-Day)"
    passed = abs(days)
    return f"{target:%Y-%m-%d} 기준 {passed}일 지났어요. (D+{passed})"


def has_explicit_exam_date(text: str) -> bool:
    if re.search(r"(?P<y>\d{4})[-\.\/](?P<m>\d{1,2})[-\.\/](?P<d>\d{1,2})", text):
        return True
    if re.search(rf"(?P<m>\d{{1,2}})\s*{K_MONTH}\s*(?P<d>\d{{1,2}})\s*{K_DAY}", text):
        return True
    if (K_EXAM in text or K_CODING_TEST in text) and re.search(rf"\d{{1,2}}\s*{K_DAY}", text):
        return True
    return False


def parse_daily_hours(text: str) -> float | None:
    m = re.search(rf"(?:{K_PER_DAY}\s*)?(?P<h>\d+(?:\.\d+)?)\s*{K_HOURS}", text)
    if not m:
        return None
    value = float(m.group("h"))
    return value if value > 0 else None


def parse_study_days(text: str) -> int | None:
    m = re.search(rf"(?P<d>\d{{1,3}})\s*{K_DAY}", text)
    if not m:
        return None
    value = int(m.group("d"))
    return value if value > 0 else None


def parse_subject_loads(text: str) -> list[SubjectLoad]:
    # Expected examples:
    # "수학 40, 영어 30, 국어 30"
    # "수학 20시간, 영어 15시간"
    subject_re = re.compile(
        r"(?P<name>[A-Za-z\uAC00-\uD7A3]{1,12})\s*(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>\uC2DC\uAC04|h|\uD398\uC774\uC9C0|\uBB38\uC81C)?"
    )

    banned = {
        K_EXAM,
        K_CODING_TEST,
        K_STUDY,
        K_PLAN,
        K_DAY,
        K_MONTH,
        K_HOUR,
        K_MIN,
        K_HOURS,
        K_PER_DAY,
        "\uB9E4\uC77C",
    }

    loads: list[SubjectLoad] = []
    for match in subject_re.finditer(text):
        name = match.group("name")
        if name in banned:
            continue
        amount = float(match.group("amount"))
        if amount <= 0:
            continue
        unit_raw = match.group("unit")
        unit = "hours" if unit_raw in {K_HOURS, "h"} else "weight"
        loads.append(SubjectLoad(name=name, amount=amount, unit=unit))

    # Deduplicate by summing same subject.
    merged: dict[str, SubjectLoad] = {}
    for load in loads:
        existing = merged.get(load.name)
        if existing is None:
            merged[load.name] = SubjectLoad(load.name, load.amount, load.unit)
        else:
            existing.amount += load.amount
            if existing.unit != load.unit:
                existing.unit = "weight"

    return list(merged.values())


def infer_subjects_without_amount(text: str) -> list[str]:
    # Supports style: "과목 수학 영어 국어".
    if K_SUBJECT not in text:
        return []
    m = re.search(rf"{K_SUBJECT}\s*(?P<body>.+)", text)
    if not m:
        return []
    body = m.group("body")
    tokens = [tok.strip(" ,.") for tok in re.split(r"[,\s]+", body) if tok.strip(" ,.")]
    subjects = [t for t in tokens if re.match(r"^[A-Za-z\uAC00-\uD7A3]{1,12}$", t)]
    return subjects[:8]


def create_exam_countdown_plan(text: str, now: datetime | None = None) -> list[ParsedEvent]:
    now = now or datetime.now()
    exam_dt = parse_exam_date(text, now)
    if exam_dt is None:
        return []

    days_left = (exam_dt.date() - now.date()).days
    if days_left <= 0:
        return []

    daily_hours_match = re.search(rf"\uD558\uB8E8\s*(?P<h>\d+(?:\.\d+)?)\s*{K_HOURS}", text)
    daily_hours = float(daily_hours_match.group("h")) if daily_hours_match else 3.0
    if daily_hours <= 0:
        daily_hours = 2.0

    loads = parse_subject_loads(text)
    if not loads:
        names = infer_subjects_without_amount(text)
        if names:
            each_weight = 1.0
            loads = [SubjectLoad(name=n, amount=each_weight, unit="weight") for n in names]
        else:
            loads = [SubjectLoad(name="General", amount=1.0, unit="weight")]

    has_hours = any(load.unit == "hours" for load in loads)
    events: list[ParsedEvent] = []

    for offset in range(1, days_left + 1):
        day = now.date() + timedelta(days=offset)
        d_left = (exam_dt.date() - day).days

        if has_hours:
            # If user gave total hours per subject, distribute remaining total by days.
            allocations: list[tuple[str, float]] = []
            for load in loads:
                subj_daily = load.amount / days_left
                allocations.append((load.name, subj_daily))
        else:
            # If user gave weights, distribute daily total hours proportionally.
            total_weight = sum(load.amount for load in loads)
            allocations = []
            for load in loads:
                subj_daily = daily_hours * (load.amount / total_weight)
                allocations.append((load.name, subj_daily))

        alloc_text = " | ".join(f"{name} {hours:.1f}h" for name, hours in allocations)
        title = f"Exam D-{d_left}: {alloc_text}"
        when = datetime.combine(day, datetime.min.time()).replace(hour=20, minute=0)
        events.append(ParsedEvent(when=when, title=title))

    exam_title = f"Exam Day ({exam_dt:%Y-%m-%d})"
    events.append(ParsedEvent(when=exam_dt.replace(hour=9, minute=0), title=exam_title))
    return events


def is_exam_distribution_request(text: str) -> bool:
    if K_EXAM not in text and K_CODING_TEST not in text:
        return False
    return (K_DISTRIBUTE in text) or (K_COUNTDOWN in text) or (K_UNTIL in text) or (K_SUBJECT in text)


def update_chat_memory(memory: ChatMemory, text: str, now: datetime | None = None) -> None:
    now = now or datetime.now()

    exam_dt = parse_exam_date(text, now)
    if exam_dt is not None:
        memory.exam_date = exam_dt

    daily_hours = parse_daily_hours(text)
    if daily_hours is not None:
        memory.daily_hours = daily_hours

    study_days = parse_study_days(text)
    if study_days is not None and (K_STUDY in text or K_PLAN in text):
        memory.study_days = study_days

    goal = extract_study_goal(text)
    if goal != "General":
        memory.study_goal = goal

    loads = parse_subject_loads(text)
    if loads:
        memory.subjects = [x.name for x in loads]
    else:
        names = infer_subjects_without_amount(text)
        if names:
            memory.subjects = names


def apply_chat_memory(text: str, memory: ChatMemory, now: datetime | None = None) -> str:
    now = now or datetime.now()
    merged = text.strip()

    if is_exam_distribution_request(merged):
        if not has_explicit_exam_date(merged) and memory.exam_date is not None:
            merged += f", {memory.exam_date.month}{K_MONTH} {memory.exam_date.day}{K_DAY} {K_EXAM}{K_UNTIL}"
        if not parse_subject_loads(merged) and not infer_subjects_without_amount(merged) and memory.subjects:
            merged += ", " + " ".join(f"{name} 1" for name in memory.subjects)
        if parse_daily_hours(merged) is None and memory.daily_hours is not None:
            merged += f", {K_PER_DAY} {memory.daily_hours:g}{K_HOURS}"

    is_study_request = (K_STUDY in merged) or (K_PLAN in merged)
    if is_study_request:
        if memory.study_goal and extract_study_goal(merged) == "General":
            if (K_STUDY in merged) or (K_PLAN in merged):
                merged = f"{memory.study_goal} {merged}"
            else:
                merged = f"{memory.study_goal}{K_STUDY}{K_PLAN} {merged}"
        if parse_study_days(merged) is None and memory.study_days is not None:
            merged += f", {memory.study_days}{K_DAY}"
        if parse_daily_hours(merged) is None and memory.daily_hours is not None:
            merged += f", {K_PER_DAY} {memory.daily_hours:g}{K_HOURS}"

    return merged


def format_chat_memory(memory: ChatMemory) -> str:
    exam = memory.exam_date.strftime("%Y-%m-%d") if memory.exam_date else "-"
    subjects = ", ".join(memory.subjects) if memory.subjects else "-"
    daily = f"{memory.daily_hours:g}h" if memory.daily_hours is not None else "-"
    goal = memory.study_goal or "-"
    days = str(memory.study_days) if memory.study_days is not None else "-"
    return f"exam={exam}; subjects={subjects}; daily_hours={daily}; study_goal={goal}; study_days={days}"


def send_telegram_notification(title: str, message: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": f"{title}\n{message}"}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except (urllib.error.URLError, urllib.error.HTTPError):
        return False


def send_kakao_notification(title: str, message: str) -> bool:
    access_token = os.getenv("KAKAO_ACCESS_TOKEN", "").strip()
    if not access_token:
        return False

    template_obj = {
        "object_type": "text",
        "text": f"{title}\n{message}",
        "link": {
            "web_url": "https://developers.kakao.com",
            "mobile_web_url": "https://developers.kakao.com",
        },
    }

    data = urllib.parse.urlencode({"template_object": json.dumps(template_obj, ensure_ascii=False)}).encode("utf-8")
    req = urllib.request.Request(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        data=data,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except (urllib.error.URLError, urllib.error.HTTPError):
        return False


def send_notification(title: str, message: str) -> None:
    if notification is not None:
        notification.notify(title=title, message=message, timeout=10)
    else:
        print(f"[NOTIFY] {title}: {message}")

    telegram_ok = send_telegram_notification(title, message)
    kakao_ok = send_kakao_notification(title, message)
    if telegram_ok:
        print("[INFO] Telegram sent.")
    if kakao_ok:
        print("[INFO] KakaoTalk sent.")


def run_daemon(db_path: Path = DB_PATH, poll_seconds: int = 15) -> None:
    print("Scheduler running. Stop with Ctrl+C")
    while True:
        now = datetime.now()
        window_start = now - timedelta(seconds=poll_seconds)
        conn = sqlite3.connect(db_path)
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
        time.sleep(poll_seconds)


def list_events(db_path: Path = DB_PATH, limit: int | None = None) -> list[tuple[int, str, str, int]]:
    conn = sqlite3.connect(db_path)
    try:
        sql = "SELECT id, title, event_time, notified FROM events ORDER BY event_time ASC"
        if limit is not None:
            rows = conn.execute(f"{sql} LIMIT ?", (limit,)).fetchall()
        else:
            rows = conn.execute(sql).fetchall()
    finally:
        conn.close()
    return rows


def remove_event(event_id: int, db_path: Path = DB_PATH) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def format_events(events: list[ParsedEvent]) -> list[str]:
    return [f"- {ev.when:%Y-%m-%d %H:%M} | {ev.title}" for ev in events]


def print_list(limit: int | None = None) -> None:
    rows = list_events(limit=limit)
    if not rows:
        print("No events.")
        return
    for event_id, title, event_time, notified in rows:
        state = "notified" if notified else "pending"
        dt = datetime.fromisoformat(event_time)
        print(f"{event_id:>3} | {dt:%Y-%m-%d %H:%M} | {title} | {state}")


def handle_ask(text: str, db_path: Path = DB_PATH) -> tuple[str, list[ParsedEvent]]:
    normalized = text.strip()
    is_study_request = (K_STUDY in normalized) or (K_PLAN in normalized)
    has_date_hint = re.search(rf"\d{{1,2}}\s*{K_DAY}", normalized) is not None
    has_time_hint = re.search(rf"\d{{1,2}}\s*{K_HOUR}", normalized) is not None
    has_explicit_month_day = (
        re.search(rf"\d{{1,2}}\s*{K_MONTH}\s*\d{{1,2}}\s*{K_DAY}", normalized) is not None
        or re.search(r"\d{4}[-\.\/]\d{1,2}[-\.\/]\d{1,2}", normalized) is not None
    )

    if is_exam_distribution_request(normalized):
        return ("exam_plan", insert_events(create_exam_countdown_plan(normalized), db_path=db_path))
    if is_study_request:
        return ("study_plan", insert_events(make_study_plan_from_text(normalized), db_path=db_path))
    if has_explicit_month_day:
        events = create_events_with_explicit_month_date(normalized)
        if events:
            return ("schedule", insert_events(events, db_path=db_path))
    if has_date_hint and has_time_hint:
        return ("schedule", add_events_from_text(normalized, db_path=db_path))
    if has_date_hint:
        date_only_event = create_date_only_event(normalized)
        if date_only_event is not None:
            return ("schedule", insert_events([date_only_event], db_path=db_path))
    return ("unknown", [])


def run_chat_mode() -> None:
    memory = load_chat_memory()
    print("Chat mode started. Type 'help' or '도움말'. Type 'exit' or '종료' to stop.")
    print("assistant> memory loaded.")
    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            save_chat_memory(memory)
            print("\nbye")
            break

        if not user_input:
            continue

        lower = user_input.lower()
        if lower in {"exit", "quit"} or K_EXIT in user_input:
            save_chat_memory(memory)
            print("assistant> 종료합니다.")
            break

        if lower == "help" or K_HELP in user_input:
            print("assistant> 예시:")
            print("assistant> - 20일 9시 면접, 1시 시험")
            print("assistant> - 영어 공부계획 14일, 하루 2시간")
            print("assistant> - 6월 30일 시험까지 역산 배분, 수학 40 영어 30 국어 30, 하루 4시간")
            print("assistant> - list, remove 3, memory, memory save, memory load, memory reset")
            continue

        if lower == "list" or K_SHOW in user_input:
            print_list(limit=20)
            continue

        if lower == "memory":
            print(f"assistant> {format_chat_memory(memory)}")
            continue

        if lower == "memory save":
            ok = save_chat_memory(memory)
            print("assistant> memory saved." if ok else "assistant> memory save failed.")
            continue

        if lower == "memory load":
            memory = load_chat_memory()
            print("assistant> memory loaded.")
            print(f"assistant> {format_chat_memory(memory)}")
            continue

        if lower in {"memory reset", "reset memory"}:
            memory = ChatMemory()
            save_chat_memory(memory)
            print("assistant> memory cleared.")
            continue

        rm_match = re.search(r"remove\s+(\d+)", lower) or re.search(rf"(\d+)\s*{K_DELETE}", user_input)
        if rm_match:
            event_id = int(rm_match.group(1))
            ok = remove_event(event_id)
            print("assistant> Removed." if ok else "assistant> Event not found.")
            continue

        enriched = apply_chat_memory(user_input, memory)
        if enriched != user_input:
            print(f"assistant> (using memory) {enriched}")

        days_left_reply = parse_days_left_query(enriched)
        if days_left_reply is not None:
            print(f"assistant> {days_left_reply}")
            update_chat_memory(memory, enriched)
            save_chat_memory(memory)
            continue

        kind, events = handle_ask(enriched)
        if not events:
            print("assistant> 이해하지 못했어요. help/도움말을 입력해 주세요.")
            continue

        update_chat_memory(memory, enriched)
        save_chat_memory(memory)

        if kind == "schedule":
            print(f"assistant> 일정 {len(events)}개 저장.")
        elif kind == "study_plan":
            print(f"assistant> 공부계획 {len(events)}개 저장.")
        elif kind == "exam_plan":
            print(f"assistant> 시험 역산 계획 {len(events)}개 저장.")
        else:
            print(f"assistant> {len(events)}개 저장.")

        for line in format_events(events[:8]):
            print(f"assistant> {line}")
        if len(events) > 8:
            print(f"assistant> ... and {len(events) - 8} more")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Natural-language Korean schedule parser + local desktop/mobile alerts"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add_cmd = sub.add_parser("add", help="Add events from Korean text")
    add_cmd.add_argument(
        "text",
        help='Example: "20일 9시 면접, 1시 시험. 21일 코딩테스트"',
    )

    ask_cmd = sub.add_parser("ask", help="One-line assistant command")
    ask_cmd.add_argument(
        "text",
        help='Example: "영어 공부계획 14일, 하루 2시간" or "6월 30일 시험까지 역산 배분, 수학 40 영어 30"',
    )

    sub.add_parser("chat", help="Interactive chat mode")
    sub.add_parser("list", help="List events")

    rm_cmd = sub.add_parser("remove", help="Remove event by ID")
    rm_cmd.add_argument("id", type=int)

    run_cmd = sub.add_parser("run", help="Run notification loop")
    run_cmd.add_argument("--poll", type=int, default=15, help="Polling interval in seconds")

    sub.add_parser("notify-test", help="Send test notification to desktop/Telegram/Kakao")
    return parser


def main() -> int:
    init_db()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "add":
        events = add_events_from_text(args.text)
        if not events:
            print("Could not parse events. Try a more explicit sentence.")
            return 1
        print(f"Added {len(events)} event(s).")
        for line in format_events(events):
            print(line)
        return 0

    if args.command == "ask":
        days_left_reply = parse_days_left_query(args.text)
        if days_left_reply is not None:
            print(days_left_reply)
            return 0

        kind, events = handle_ask(args.text)
        if not events:
            print("Could not understand request. Try schedule/study/exam-plan wording.")
            return 1
        label = {
            "schedule": "Added schedule",
            "study_plan": "Created study plan",
            "exam_plan": "Created exam countdown plan",
        }.get(kind, "Saved")
        print(f"{label}: {len(events)} event(s).")
        for line in format_events(events[:20]):
            print(line)
        if len(events) > 20:
            print(f"... and {len(events) - 20} more.")
        return 0

    if args.command == "chat":
        run_chat_mode()
        return 0

    if args.command == "list":
        print_list()
        return 0

    if args.command == "remove":
        removed = remove_event(args.id)
        print("Removed." if removed else "Event not found.")
        return 0 if removed else 1

    if args.command == "run":
        run_daemon(poll_seconds=args.poll)
        return 0

    if args.command == "notify-test":
        send_notification("Assistant Test", "Desktop/Telegram/Kakao test message")
        print("Test notification attempted. Check desktop/app.")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

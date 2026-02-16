from __future__ import annotations

import sqlite3
import threading
import time
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import messagebox, ttk

from assistant import (
    DB_PATH,
    ChatMemory,
    apply_chat_memory,
    format_chat_memory,
    format_events,
    handle_ask,
    init_db,
    list_events,
    load_chat_memory,
    remove_event,
    save_chat_memory,
    send_notification,
    update_chat_memory,
)


class NotifierWorker(threading.Thread):
    def __init__(self, stop_event: threading.Event, poll_seconds: int = 15) -> None:
        super().__init__(daemon=True)
        self.stop_event = stop_event
        self.poll_seconds = poll_seconds

    def run(self) -> None:
        while not self.stop_event.is_set():
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

            self.stop_event.wait(self.poll_seconds)


class AssistantGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Princess Schedule Assistant")
        self.root.geometry("1120x740")
        self.root.configure(bg="#fff7fb")

        init_db()
        self.memory: ChatMemory = load_chat_memory()
        self.notifier_stop = threading.Event()
        self.notifier_thread: NotifierWorker | None = None
        self.notifier_status = tk.StringVar(value="Notifier: Off")

        self._apply_princess_theme()
        self._build_ui()
        self._append_assistant("GUI started. Type your request and press Send.")
        self._append_assistant("Example: 20일 9시 면접, 1시 시험")
        self._append_assistant("Example: 6월 30일 시험까지 역산 배분, 수학 40 영어 30 국어 30, 하루 4시간")
        self.refresh_events()

    def _apply_princess_theme(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(
            "Root.TFrame",
            background="#fff7fb",
        )
        style.configure(
            "Princess.TLabel",
            background="#fff7fb",
            foreground="#7a2f4b",
            font=("Malgun Gothic", 10, "bold"),
        )
        style.configure(
            "PrincessTitle.TLabel",
            background="#fff7fb",
            foreground="#b13b67",
            font=("Malgun Gothic", 16, "bold"),
        )
        style.configure(
            "PrincessSub.TLabel",
            background="#fff7fb",
            foreground="#9b4a68",
            font=("Malgun Gothic", 10),
        )
        style.configure(
            "Chip.TLabel",
            background="#ffe4ee",
            foreground="#8a2f52",
            padding=(10, 4),
            font=("Malgun Gothic", 9, "bold"),
        )
        style.configure(
            "Princess.TLabelframe",
            background="#fff7fb",
            bordercolor="#f2bfd0",
            relief="solid",
        )
        style.configure(
            "Princess.TLabelframe.Label",
            background="#fff7fb",
            foreground="#a83b65",
            font=("Malgun Gothic", 10, "bold"),
        )
        style.configure(
            "Princess.TButton",
            background="#f7c7d8",
            foreground="#5a1f37",
            bordercolor="#d98aa6",
            focusthickness=1,
            focuscolor="#f7dbe5",
            padding=(10, 7),
            font=("Malgun Gothic", 10, "bold"),
        )
        style.map(
            "Princess.TButton",
            background=[("active", "#f3b8cc"), ("pressed", "#e9a2bc")],
            foreground=[("disabled", "#987184")],
        )
        style.configure(
            "Princess.TEntry",
            fieldbackground="#ffffff",
            foreground="#4b1f31",
            bordercolor="#e0a8bc",
            lightcolor="#f8dce7",
            darkcolor="#e0a8bc",
            padding=(8, 6),
            font=("Malgun Gothic", 10),
        )
        style.configure(
            "Princess.TNotebook",
            background="#fff7fb",
            borderwidth=0,
            tabmargins=(2, 2, 2, 0),
        )
        style.configure(
            "Princess.TNotebook.Tab",
            background="#f9dbe7",
            foreground="#7a2f4b",
            padding=(14, 8),
            font=("Malgun Gothic", 10, "bold"),
        )
        style.map(
            "Princess.TNotebook.Tab",
            background=[("selected", "#f7c7d8"), ("active", "#f2ccda")],
            foreground=[("selected", "#5b2038")],
        )
        style.configure(
            "Princess.Treeview",
            background="#fffdfd",
            fieldbackground="#fffdfd",
            foreground="#4b1f31",
            bordercolor="#f0c3d2",
            rowheight=27,
            font=("Malgun Gothic", 10),
        )
        style.configure(
            "Princess.Treeview.Heading",
            background="#f8d3e1",
            foreground="#6e2943",
            font=("Malgun Gothic", 10, "bold"),
            relief="flat",
        )
        style.map(
            "Princess.Treeview",
            background=[("selected", "#f6c8da")],
            foreground=[("selected", "#4b1f31")],
        )

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=3)
        self.root.columnconfigure(1, weight=2)
        self.root.rowconfigure(0, weight=1)

        left = ttk.Frame(self.root, padding=10, style="Root.TFrame")
        left.grid(row=0, column=0, sticky="nsew")
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(self.root, padding=10, style="Root.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        header = ttk.Frame(left, style="Root.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Princess Diary Planner", style="PrincessTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text=f"Today: {datetime.now():%Y-%m-%d} | 작은 습관이 큰 결과를 만들어요",
            style="PrincessSub.TLabel",
        ).grid(row=1, column=0, sticky="w")
        ttk.Label(header, textvariable=self.notifier_status, style="Chip.TLabel").grid(row=0, column=1, rowspan=2, sticky="e")

        self.chat = tk.Text(
            left,
            wrap="word",
            state="disabled",
            bg="#fffafc",
            fg="#5a1f37",
            insertbackground="#8c3657",
            relief="solid",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground="#efbfd1",
            font=("Malgun Gothic", 11),
            padx=8,
            pady=8,
        )
        self.chat.grid(row=1, column=0, sticky="nsew")
        self.chat.tag_configure("assistant", foreground="#7a2f4b")
        self.chat.tag_configure("you", foreground="#2f4f6b")
        self.chat.tag_configure("meta", foreground="#9b6a7f")

        input_frame = ttk.Frame(left, style="Root.TFrame")
        input_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        input_frame.columnconfigure(0, weight=1)

        self.entry = ttk.Entry(input_frame, style="Princess.TEntry")
        self.entry.grid(row=0, column=0, sticky="ew")
        self.entry.bind("<Return>", lambda _e: self.on_send())

        ttk.Button(input_frame, text="Send", style="Princess.TButton", command=self.on_send).grid(
            row=0, column=1, padx=(6, 0)
        )

        mem_frame = ttk.LabelFrame(left, text="Memory", padding=8, style="Princess.TLabelframe")
        mem_frame.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        mem_frame.columnconfigure(0, weight=1)

        self.memory_label = ttk.Label(mem_frame, text=format_chat_memory(self.memory), style="Princess.TLabel")
        self.memory_label.grid(row=0, column=0, sticky="w")

        mem_buttons = ttk.Frame(mem_frame, style="Root.TFrame")
        mem_buttons.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(mem_buttons, text="Save", style="Princess.TButton", command=self.on_memory_save).grid(
            row=0, column=0, padx=(0, 6)
        )
        ttk.Button(mem_buttons, text="Load", style="Princess.TButton", command=self.on_memory_load).grid(
            row=0, column=1, padx=(0, 6)
        )
        ttk.Button(mem_buttons, text="Reset", style="Princess.TButton", command=self.on_memory_reset).grid(
            row=0, column=2
        )

        ttk.Label(right, text="Planner Views", style="PrincessTitle.TLabel").grid(row=0, column=0, sticky="w")

        self.notebook = ttk.Notebook(right, style="Princess.TNotebook")
        self.notebook.grid(row=1, column=0, sticky="nsew")

        tab_all = ttk.Frame(self.notebook)
        tab_today = ttk.Frame(self.notebook)
        tab_week = ttk.Frame(self.notebook)
        tab_all.rowconfigure(0, weight=1)
        tab_all.columnconfigure(0, weight=1)
        tab_today.rowconfigure(0, weight=1)
        tab_today.columnconfigure(0, weight=1)
        tab_week.rowconfigure(0, weight=1)
        tab_week.columnconfigure(0, weight=1)
        self.notebook.add(tab_all, text="All Events")
        self.notebook.add(tab_today, text="Today")
        self.notebook.add(tab_week, text="Week Calendar")

        self.tree_all = ttk.Treeview(
            tab_all,
            columns=("id", "time", "title", "state"),
            show="headings",
            height=24,
            style="Princess.Treeview",
        )
        self.tree_all.heading("id", text="ID")
        self.tree_all.heading("time", text="Time")
        self.tree_all.heading("title", text="Title")
        self.tree_all.heading("state", text="State")
        self.tree_all.column("id", width=50, anchor="center")
        self.tree_all.column("time", width=140, anchor="center")
        self.tree_all.column("title", width=300, anchor="w")
        self.tree_all.column("state", width=80, anchor="center")
        self.tree_all.grid(row=0, column=0, sticky="nsew")

        self.tree_today = ttk.Treeview(
            tab_today,
            columns=("id", "time", "title", "state"),
            show="headings",
            height=24,
            style="Princess.Treeview",
        )
        self.tree_today.heading("id", text="ID")
        self.tree_today.heading("time", text="Time")
        self.tree_today.heading("title", text="Title")
        self.tree_today.heading("state", text="State")
        self.tree_today.column("id", width=50, anchor="center")
        self.tree_today.column("time", width=90, anchor="center")
        self.tree_today.column("title", width=320, anchor="w")
        self.tree_today.column("state", width=80, anchor="center")
        self.tree_today.grid(row=0, column=0, sticky="nsew")

        self.tree_week = ttk.Treeview(
            tab_week,
            columns=("day", "date", "count", "items"),
            show="headings",
            height=24,
            style="Princess.Treeview",
        )
        self.tree_week.heading("day", text="Day")
        self.tree_week.heading("date", text="Date")
        self.tree_week.heading("count", text="Count")
        self.tree_week.heading("items", text="Tasks")
        self.tree_week.column("day", width=70, anchor="center")
        self.tree_week.column("date", width=100, anchor="center")
        self.tree_week.column("count", width=60, anchor="center")
        self.tree_week.column("items", width=350, anchor="w")
        self.tree_week.grid(row=0, column=0, sticky="nsew")

        btns = ttk.Frame(right, style="Root.TFrame")
        btns.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(btns, text="Refresh", style="Princess.TButton", command=self.refresh_events).grid(
            row=0, column=0, padx=(0, 6)
        )
        ttk.Button(btns, text="Delete Selected", style="Princess.TButton", command=self.delete_selected).grid(
            row=0, column=1, padx=(0, 6)
        )
        ttk.Button(btns, text="Start Notifier", style="Princess.TButton", command=self.start_notifier).grid(
            row=0, column=2, padx=(0, 6)
        )
        ttk.Button(btns, text="Stop Notifier", style="Princess.TButton", command=self.stop_notifier).grid(
            row=0, column=3
        )

    def _append(self, who: str, text: str) -> None:
        self.chat.configure(state="normal")
        tag = "assistant" if who == "assistant" else "you"
        self.chat.insert("end", f"{who}> ", ("meta",))
        self.chat.insert("end", f"{text}\n", (tag,))
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def _append_assistant(self, text: str) -> None:
        self._append("assistant", text)

    def _clear_chat(self) -> None:
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")

    def on_send(self) -> None:
        user_input = self.entry.get().strip()
        if not user_input:
            return
        self.entry.delete(0, "end")
        self._append("you", user_input)

        enriched = apply_chat_memory(user_input, self.memory)
        if enriched != user_input:
            self._append_assistant(f"(using memory) {enriched}")

        kind, events = handle_ask(enriched)
        if not events:
            self._append_assistant("I could not parse that. Try schedule/study/exam-plan wording.")
            return

        update_chat_memory(self.memory, enriched)
        save_chat_memory(self.memory)
        self.memory_label.configure(text=format_chat_memory(self.memory))

        if kind == "schedule":
            self._append_assistant(f"Added schedule: {len(events)} event(s).")
        elif kind == "study_plan":
            self._append_assistant(f"Created study plan: {len(events)} event(s).")
        elif kind == "exam_plan":
            self._append_assistant(f"Created exam countdown plan: {len(events)} event(s).")
        else:
            self._append_assistant(f"Saved: {len(events)} event(s).")

        for line in format_events(events[:6]):
            self._append_assistant(line)
        if len(events) > 6:
            self._append_assistant(f"... and {len(events) - 6} more")

        self.refresh_events()

    def refresh_events(self) -> None:
        for row in self.tree_all.get_children():
            self.tree_all.delete(row)
        for row in self.tree_today.get_children():
            self.tree_today.delete(row)
        for row in self.tree_week.get_children():
            self.tree_week.delete(row)

        rows = list_events()
        for event_id, title, event_time, notified in rows:
            dt = datetime.fromisoformat(event_time)
            state = "notified" if notified else "pending"
            self.tree_all.insert("", "end", values=(event_id, dt.strftime("%Y-%m-%d %H:%M"), title, state))

        today = datetime.now().date()
        for event_id, title, event_time, notified in rows:
            dt = datetime.fromisoformat(event_time)
            if dt.date() != today:
                continue
            state = "notified" if notified else "pending"
            self.tree_today.insert("", "end", values=(event_id, dt.strftime("%H:%M"), title, state))

        by_day: dict[date, list[str]] = {}
        for i in range(7):
            d = today + timedelta(days=i)
            by_day[d] = []
        for _id, title, event_time, _notified in rows:
            dt = datetime.fromisoformat(event_time)
            d = dt.date()
            if d in by_day:
                by_day[d].append(f"{dt:%H:%M} {title}")

        for i in range(7):
            d = today + timedelta(days=i)
            items = by_day[d]
            day_name = d.strftime("%a")
            summary = " | ".join(items[:4])
            if len(items) > 4:
                summary += f" | ... +{len(items) - 4}"
            self.tree_week.insert(
                "",
                "end",
                values=(day_name, d.strftime("%Y-%m-%d"), len(items), summary),
            )

    def delete_selected(self) -> None:
        tab_id = self.notebook.select()
        tab_text = self.notebook.tab(tab_id, "text")
        if tab_text == "Today":
            tree = self.tree_today
        elif tab_text == "All Events":
            tree = self.tree_all
        else:
            messagebox.showinfo("Delete", "Delete is available in All Events or Today tab.")
            return

        selected = tree.selection()
        if not selected:
            messagebox.showinfo("Delete", "Select an event first.")
            return
        item = tree.item(selected[0])
        event_id = int(item["values"][0])
        ok = remove_event(event_id)
        if ok:
            self._append_assistant(f"Removed event {event_id}.")
            self.refresh_events()
        else:
            messagebox.showwarning("Delete", "Event not found.")

    def on_memory_save(self) -> None:
        ok = save_chat_memory(self.memory)
        self._append_assistant("Memory saved." if ok else "Memory save failed.")

    def on_memory_load(self) -> None:
        self.memory = load_chat_memory()
        self.memory_label.configure(text=format_chat_memory(self.memory))
        self._append_assistant("Memory loaded.")

    def on_memory_reset(self) -> None:
        should_clear = messagebox.askyesno(
            "Reset",
            "Reset memory and clear all events + chat log?",
        )
        if not should_clear:
            return

        self.memory = ChatMemory()
        save_chat_memory(self.memory)
        self.memory_label.configure(text=format_chat_memory(self.memory))
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("DELETE FROM events")
            conn.commit()
        finally:
            conn.close()
        self.refresh_events()
        self._clear_chat()
        self._append_assistant("Reset complete. Memory, chat, and events were cleared.")

    def start_notifier(self) -> None:
        if self.notifier_thread is not None and self.notifier_thread.is_alive():
            self._append_assistant("Notifier is already running.")
            return
        self.notifier_stop.clear()
        self.notifier_thread = NotifierWorker(self.notifier_stop, poll_seconds=15)
        self.notifier_thread.start()
        self.notifier_status.set("Notifier: On")
        self._append_assistant("Notifier started.")

    def stop_notifier(self) -> None:
        if self.notifier_thread is None or not self.notifier_thread.is_alive():
            self._append_assistant("Notifier is not running.")
            return
        self.notifier_stop.set()
        self.notifier_status.set("Notifier: Off")
        self._append_assistant("Notifier stopped.")


def main() -> None:
    root = tk.Tk()
    app = AssistantGUI(root)

    def on_close() -> None:
        app.stop_notifier()
        save_chat_memory(app.memory)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()

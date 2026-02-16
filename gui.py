from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, font as tkfont
from tkinter import messagebox, ttk

try:
    from PIL import Image, ImageOps, ImageTk
except Exception:  # pragma: no cover
    Image = None
    ImageOps = None
    ImageTk = None

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


SETTINGS_PATH = Path("gui_settings.json")
ASSETS_DIR = Path("assets")
USER_ILLUST_PATH = ASSETS_DIR / "user_illustration.png"

K_EXAM = "\uC2DC\uD5D8"
K_CODE_TEST = "\uCF54\uB529\uD14C\uC2A4\uD2B8"
K_INTERVIEW = "\uBA74\uC811"
K_STUDY = "\uACF5\uBD80"

THEMES: dict[str, dict[str, str]] = {
    "princess": {
        "bg": "#fff7fb",
        "panel": "#fffafc",
        "text": "#57263b",
        "subtext": "#8c4863",
        "accent": "#f7c7d8",
        "accent_dark": "#d980a2",
        "button_bg": "#f7c7d8",
        "button_active": "#f1b7cd",
        "entry_border": "#e2a8be",
        "chip_bg": "#ffe4ee",
        "chip_fg": "#8a2f52",
        "tree_bg": "#fffdfd",
        "tree_head": "#f8d3e1",
        "selected": "#f6c8da",
    },
    "mint": {
        "bg": "#f3fff9",
        "panel": "#f7fffb",
        "text": "#21493c",
        "subtext": "#3f7364",
        "accent": "#bfeedd",
        "accent_dark": "#70b59b",
        "button_bg": "#c7f2e3",
        "button_active": "#b1e7d4",
        "entry_border": "#8dc9b3",
        "chip_bg": "#ddf8ee",
        "chip_fg": "#22614e",
        "tree_bg": "#fcfffe",
        "tree_head": "#d9f6eb",
        "selected": "#c9eddf",
    },
    "simple": {
        "bg": "#f7f7f7",
        "panel": "#ffffff",
        "text": "#2f2f2f",
        "subtext": "#5f5f5f",
        "accent": "#e4e4e4",
        "accent_dark": "#b9b9b9",
        "button_bg": "#e8e8e8",
        "button_active": "#d9d9d9",
        "entry_border": "#bfbfbf",
        "chip_bg": "#ececec",
        "chip_fg": "#3c3c3c",
        "tree_bg": "#ffffff",
        "tree_head": "#eeeeee",
        "selected": "#dddddd",
    },
}

PRIORITY_ORDER = {"exam": 3, "interview": 2, "study": 1, "normal": 0}


def load_gui_settings() -> dict[str, str]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_gui_settings(settings: dict[str, str]) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


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
        self.root.title("Diary Schedule Assistant")
        self.root.geometry("1220x780")
        self.root.minsize(1120, 700)

        init_db()
        self.memory: ChatMemory = load_chat_memory()
        self.notifier_stop = threading.Event()
        self.notifier_thread: NotifierWorker | None = None
        self.notifier_status = tk.StringVar(value="Notifier: Off")
        self.current_theme = tk.StringVar(value="princess")
        self.active_view = "all"
        self.ui_font = self._pick_ui_font()
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.settings = load_gui_settings()
        self.illust_image: tk.PhotoImage | None = None
        self.illust_source_pil = None
        self.illust_scale = tk.IntVar(value=int(self.settings.get("illust_scale", "100")))
        self.illust_offset_x = tk.IntVar(value=int(self.settings.get("illust_offset_x", "0")))
        self.illust_offset_y = tk.IntVar(value=int(self.settings.get("illust_offset_y", "0")))
        self.illust_w = tk.IntVar(value=int(self.settings.get("illust_w", "260")))
        self.illust_h = tk.IntVar(value=int(self.settings.get("illust_h", "96")))

        self._build_ui()
        self._apply_theme(self.current_theme.get())
        self._append_assistant("Ready.")
        self.refresh_events()

    def _pick_ui_font(self) -> str:
        families = set(tkfont.families(self.root))
        if "Pretendard" in families:
            return "Pretendard"
        if "Pretendard Variable" in families:
            return "Pretendard Variable"
        return "Malgun Gothic"

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=3)
        self.root.columnconfigure(1, weight=2)
        self.root.rowconfigure(0, weight=1)

        self.left = ttk.Frame(self.root, padding=10, style="Root.TFrame")
        self.left.grid(row=0, column=0, sticky="nsew")
        self.left.rowconfigure(1, weight=1)
        self.left.columnconfigure(0, weight=1)

        self.right = ttk.Frame(self.root, padding=10, style="Root.TFrame")
        self.right.grid(row=0, column=1, sticky="nsew")
        self.right.rowconfigure(2, weight=1)
        self.right.columnconfigure(0, weight=1)

        header = ttk.Frame(self.left, style="Root.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)
        header.columnconfigure(2, weight=0)

        self.title_label = ttk.Label(header, text="Diary Planner", style="Title.TLabel")
        self.title_label.grid(row=0, column=0, sticky="w")
        self.subtitle_label = ttk.Label(header, text=f"Today: {datetime.now():%Y-%m-%d}", style="Sub.TLabel")
        self.subtitle_label.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.status_chip = ttk.Label(header, textvariable=self.notifier_status, style="Chip.TLabel")
        self.status_chip.grid(row=0, column=1, sticky="e", padx=(10, 10), pady=(2, 0))

        theme_bar = ttk.Frame(header, style="Root.TFrame")
        theme_bar.grid(row=2, column=0, columnspan=2, pady=(8, 0), sticky="w")
        ttk.Label(theme_bar, text="Theme", style="Sub.TLabel").grid(row=0, column=0, padx=(0, 6))
        ttk.Button(theme_bar, text="Princess", style="App.TButton", command=lambda: self._set_theme("princess")).grid(
            row=0, column=1, padx=2
        )
        ttk.Button(theme_bar, text="Mint", style="App.TButton", command=lambda: self._set_theme("mint")).grid(row=0, column=2, padx=2)
        ttk.Button(theme_bar, text="Simple", style="App.TButton", command=lambda: self._set_theme("simple")).grid(
            row=0, column=3, padx=2
        )

        self.illustration = tk.Canvas(header, width=260, height=96, highlightthickness=0, relief="flat")
        self.illustration.grid(row=0, column=2, rowspan=3, padx=(6, 0), sticky="e")
        ttk.Button(header, text="Use My Image", style="App.TButton", command=self.on_pick_illustration).grid(
            row=3, column=2, sticky="e", pady=(6, 0), padx=(0, 2)
        )
        self._build_illustration_controls(header)

        self.chat = tk.Text(
            self.left,
            wrap="word",
            state="disabled",
            relief="solid",
            borderwidth=1,
            highlightthickness=1,
            font=(self.ui_font, 11),
            padx=8,
            pady=8,
        )
        self.chat.grid(row=1, column=0, sticky="nsew")
        self.chat.tag_configure("assistant", foreground="#6d2f47")
        self.chat.tag_configure("you", foreground="#284a67")
        self.chat.tag_configure("meta", foreground="#9b6a7f")

        input_frame = ttk.Frame(self.left, style="Root.TFrame")
        input_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        input_frame.columnconfigure(0, weight=1)
        self.entry = ttk.Entry(input_frame, style="App.TEntry")
        self.entry.grid(row=0, column=0, sticky="ew")
        self.entry.bind("<Return>", lambda _e: self.on_send())
        ttk.Button(input_frame, text="Send", style="App.TButton", command=self.on_send).grid(row=0, column=1, padx=(6, 0))

        mem_frame = ttk.LabelFrame(self.left, text="Memory", padding=8, style="App.TLabelframe")
        mem_frame.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        mem_frame.columnconfigure(0, weight=1)
        self.memory_label = ttk.Label(mem_frame, text=format_chat_memory(self.memory), style="App.TLabel")
        self.memory_label.grid(row=0, column=0, sticky="w")
        mem_buttons = ttk.Frame(mem_frame, style="Root.TFrame")
        mem_buttons.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(mem_buttons, text="Save", style="App.TButton", command=self.on_memory_save).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(mem_buttons, text="Load", style="App.TButton", command=self.on_memory_load).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(mem_buttons, text="Reset", style="App.TButton", command=self.on_memory_reset).grid(row=0, column=2)

        self.view_label = ttk.Label(self.right, text="Planner Views", style="Title.TLabel")
        self.view_label.grid(row=0, column=0, sticky="w")

        tab_bar = ttk.Frame(self.right, style="Root.TFrame")
        tab_bar.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        self.tab_all_btn = ttk.Button(tab_bar, text="All Events", style="TabActive.TButton", command=lambda: self._switch_view("all"))
        self.tab_today_btn = ttk.Button(tab_bar, text="Today", style="Tab.TButton", command=lambda: self._switch_view("today"))
        self.tab_week_btn = ttk.Button(tab_bar, text="Week Calendar", style="Tab.TButton", command=lambda: self._switch_view("week"))
        self.tab_all_btn.grid(row=0, column=0, padx=(0, 6))
        self.tab_today_btn.grid(row=0, column=1, padx=(0, 6))
        self.tab_week_btn.grid(row=0, column=2)

        self.view_stack = ttk.Frame(self.right, style="Root.TFrame")
        self.view_stack.grid(row=2, column=0, sticky="nsew")
        self.view_stack.rowconfigure(0, weight=1)
        self.view_stack.columnconfigure(0, weight=1)

        tab_all = ttk.Frame(self.view_stack, style="Root.TFrame")
        tab_today = ttk.Frame(self.view_stack, style="Root.TFrame")
        tab_week = ttk.Frame(self.view_stack, style="Root.TFrame")
        self.view_frames = {"all": tab_all, "today": tab_today, "week": tab_week}
        for frame in self.view_frames.values():
            frame.grid(row=0, column=0, sticky="nsew")
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(0, weight=1)

        self.tree_all = ttk.Treeview(tab_all, columns=("id", "time", "title", "state"), show="headings", style="App.Treeview")
        self.tree_all.heading("id", text="ID")
        self.tree_all.heading("time", text="Time")
        self.tree_all.heading("title", text="Title")
        self.tree_all.heading("state", text="State")
        self.tree_all.column("id", width=50, anchor="center")
        self.tree_all.column("time", width=124, anchor="center")
        self.tree_all.column("title", width=230, anchor="w")
        self.tree_all.column("state", width=66, anchor="center")
        self.tree_all.grid(row=0, column=0, sticky="nsew")
        all_x = ttk.Scrollbar(tab_all, orient="horizontal", command=self.tree_all.xview)
        self.tree_all.configure(xscrollcommand=all_x.set)
        all_x.grid(row=1, column=0, sticky="ew")

        self.tree_today = ttk.Treeview(tab_today, columns=("id", "time", "title", "state"), show="headings", style="App.Treeview")
        self.tree_today.heading("id", text="ID")
        self.tree_today.heading("time", text="Time")
        self.tree_today.heading("title", text="Title")
        self.tree_today.heading("state", text="State")
        self.tree_today.column("id", width=50, anchor="center")
        self.tree_today.column("time", width=80, anchor="center")
        self.tree_today.column("title", width=264, anchor="w")
        self.tree_today.column("state", width=70, anchor="center")
        self.tree_today.grid(row=0, column=0, sticky="nsew")
        today_x = ttk.Scrollbar(tab_today, orient="horizontal", command=self.tree_today.xview)
        self.tree_today.configure(xscrollcommand=today_x.set)
        today_x.grid(row=1, column=0, sticky="ew")

        self.tree_week = ttk.Treeview(
            tab_week,
            columns=("sticker", "day", "date", "count", "items"),
            show="headings",
            style="App.Treeview",
        )
        self.tree_week.heading("sticker", text="Sticker")
        self.tree_week.heading("day", text="Day")
        self.tree_week.heading("date", text="Date")
        self.tree_week.heading("count", text="Count")
        self.tree_week.heading("items", text="Tasks")
        self.tree_week.column("sticker", width=70, anchor="center")
        self.tree_week.column("day", width=70, anchor="center")
        self.tree_week.column("date", width=110, anchor="center")
        self.tree_week.column("count", width=60, anchor="center")
        self.tree_week.column("items", width=320, anchor="w")
        self.tree_week.grid(row=0, column=0, sticky="nsew")
        week_x = ttk.Scrollbar(tab_week, orient="horizontal", command=self.tree_week.xview)
        self.tree_week.configure(xscrollcommand=week_x.set)
        week_x.grid(row=1, column=0, sticky="ew")

        btns = ttk.Frame(self.right, style="Root.TFrame")
        btns.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(btns, text="Refresh", style="App.TButton", command=self.refresh_events).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(btns, text="Delete Selected", style="App.TButton", command=self.delete_selected).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(btns, text="Start Notifier", style="App.TButton", command=self.start_notifier).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(btns, text="Stop Notifier", style="App.TButton", command=self.stop_notifier).grid(row=0, column=3)

        self._switch_view("all")

    def _set_theme(self, theme_name: str) -> None:
        self.current_theme.set(theme_name)
        self.settings["theme"] = theme_name
        save_gui_settings(self.settings)
        self._apply_theme(theme_name)

    def _build_illustration_controls(self, header: ttk.Frame) -> None:
        ctrl = ttk.LabelFrame(header, text="Image Layout", padding=6, style="App.TLabelframe")
        ctrl.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        ctrl.columnconfigure(1, weight=1)

        ttk.Label(ctrl, text="Scale %", style="Sub.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Scale(
            ctrl,
            from_=40,
            to=220,
            variable=self.illust_scale,
            orient="horizontal",
            command=lambda _v: self._on_illust_transform_change(),
        ).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        ttk.Label(ctrl, text="Offset X", style="Sub.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Scale(
            ctrl,
            from_=-160,
            to=160,
            variable=self.illust_offset_x,
            orient="horizontal",
            command=lambda _v: self._on_illust_transform_change(),
        ).grid(row=1, column=1, sticky="ew", padx=(6, 0))

        ttk.Label(ctrl, text="Offset Y", style="Sub.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Scale(
            ctrl,
            from_=-100,
            to=100,
            variable=self.illust_offset_y,
            orient="horizontal",
            command=lambda _v: self._on_illust_transform_change(),
        ).grid(row=2, column=1, sticky="ew", padx=(6, 0))

        size_row = ttk.Frame(ctrl, style="Root.TFrame")
        size_row.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(size_row, text="Canvas W", style="Sub.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(size_row, from_=180, to=480, textvariable=self.illust_w, width=6).grid(row=0, column=1, padx=(6, 10))
        ttk.Label(size_row, text="H", style="Sub.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(size_row, from_=80, to=240, textvariable=self.illust_h, width=6).grid(row=0, column=3, padx=(6, 10))
        ttk.Button(size_row, text="Apply Size", style="App.TButton", command=self.on_apply_illust_size).grid(row=0, column=4, padx=(0, 8))
        ttk.Button(size_row, text="Reset Image", style="App.TButton", command=self.on_reset_illust_transform).grid(row=0, column=5)

    def _apply_theme(self, theme_name: str) -> None:
        palette = THEMES.get(theme_name, THEMES["princess"])
        self.root.configure(bg=palette["bg"])

        self.style.configure("Root.TFrame", background=palette["bg"])
        self.style.configure("App.TLabel", background=palette["bg"], foreground=palette["text"], font=(self.ui_font, 10, "bold"))
        self.style.configure("Title.TLabel", background=palette["bg"], foreground=palette["text"], font=(self.ui_font, 18, "bold"))
        self.style.configure("Sub.TLabel", background=palette["bg"], foreground=palette["subtext"], font=(self.ui_font, 11))
        self.style.configure("Chip.TLabel", background=palette["chip_bg"], foreground=palette["chip_fg"], padding=(10, 4), font=(self.ui_font, 10, "bold"))

        self.style.configure("App.TLabelframe", background=palette["bg"], bordercolor=palette["accent_dark"], relief="solid")
        self.style.configure("App.TLabelframe.Label", background=palette["bg"], foreground=palette["text"], font=(self.ui_font, 10, "bold"))

        self.style.configure(
            "App.TButton",
            background=palette["button_bg"],
            foreground=palette["text"],
            bordercolor=palette["accent_dark"],
            padding=(10, 7),
            font=(self.ui_font, 10, "bold"),
            relief="flat",
            borderwidth=0,
        )
        self.style.map("App.TButton", background=[("active", palette["button_active"]), ("pressed", palette["button_active"])])

        self.style.configure(
            "Tab.TButton",
            background=palette["accent"],
            foreground=palette["text"],
            bordercolor=palette["accent_dark"],
            padding=(16, 10),
            font=(self.ui_font, 11, "bold"),
            relief="flat",
            borderwidth=0,
        )
        self.style.map("Tab.TButton", background=[("active", palette["button_bg"]), ("pressed", palette["button_bg"])])
        self.style.configure(
            "TabActive.TButton",
            background=palette["button_bg"],
            foreground=palette["text"],
            bordercolor=palette["accent_dark"],
            padding=(16, 10),
            font=(self.ui_font, 11, "bold"),
            relief="flat",
            borderwidth=0,
        )
        self.style.map("TabActive.TButton", background=[("active", palette["button_bg"]), ("pressed", palette["button_bg"])])

        self.style.configure(
            "App.TEntry",
            fieldbackground="#ffffff",
            foreground=palette["text"],
            bordercolor=palette["entry_border"],
            lightcolor=palette["accent"],
            darkcolor=palette["entry_border"],
            padding=(8, 6),
            font=(self.ui_font, 10),
        )

        self.style.configure(
            "App.Treeview",
            background=palette["tree_bg"],
            fieldbackground=palette["tree_bg"],
            foreground=palette["text"],
            bordercolor=palette["accent"],
            rowheight=27,
            font=(self.ui_font, 10),
        )
        self.style.configure(
            "App.Treeview.Heading",
            background=palette["tree_head"],
            foreground=palette["text"],
            font=(self.ui_font, 11, "bold"),
            relief="flat",
            borderwidth=0,
        )
        self.style.map("App.Treeview", background=[("selected", palette["selected"])], foreground=[("selected", palette["text"])])

        self.chat.configure(
            bg=palette["panel"],
            fg=palette["text"],
            insertbackground=palette["text"],
            highlightbackground=palette["accent_dark"],
            highlightcolor=palette["accent_dark"],
        )
        self.chat.tag_configure("assistant", foreground=palette["text"])
        self.chat.tag_configure("you", foreground="#2f4f6b" if theme_name != "simple" else "#2f2f2f")
        self.chat.tag_configure("meta", foreground=palette["subtext"])

        self._configure_priority_tags()
        self._update_tab_styles()
        self._render_illustration(palette)
        self.refresh_events()

    def _render_illustration(self, palette: dict[str, str]) -> None:
        self.illustration.configure(bg=palette["panel"])
        self.illustration.delete("all")

        image_path = self.settings.get("illustration_path", str(USER_ILLUST_PATH))
        if self._draw_user_image(image_path):
            return

        self._draw_fallback_illustration(palette)

    def _draw_user_image(self, path_str: str) -> bool:
        path = Path(path_str)
        if not path.exists():
            return False
        if Image is None or ImageOps is None or ImageTk is None:
            try:
                self.illust_image = tk.PhotoImage(file=str(path))
            except tk.TclError:
                return False
            cw = int(self.illustration.cget("width"))
            ch = int(self.illustration.cget("height"))
            self.illustration.create_image(cw // 2, ch // 2, image=self.illust_image)
            self.illustration.create_rectangle(4, 4, cw - 4, ch - 4, outline="#d9a2b8", width=1)
            return True

        try:
            cache_key = self.settings.get("_loaded_path", "")
            if self.illust_source_pil is None or cache_key != str(path):
                self.illust_source_pil = Image.open(path).convert("RGBA")
                self.settings["_loaded_path"] = str(path)
        except Exception:
            return False

        cw = max(180, int(self.illust_w.get()))
        ch = max(80, int(self.illust_h.get()))
        self.illustration.configure(width=cw, height=ch)

        base = ImageOps.contain(self.illust_source_pil, (cw, ch), Image.Resampling.LANCZOS)
        scale = max(10, int(self.illust_scale.get())) / 100.0
        sw = max(1, int(base.width * scale))
        sh = max(1, int(base.height * scale))
        scaled = base.resize((sw, sh), Image.Resampling.LANCZOS)

        canvas_img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        x = (cw - sw) // 2 + int(self.illust_offset_x.get())
        y = (ch - sh) // 2 + int(self.illust_offset_y.get())
        canvas_img.paste(scaled, (x, y), scaled)

        self.illust_image = ImageTk.PhotoImage(canvas_img)
        self.illustration.create_image(cw // 2, ch // 2, image=self.illust_image)
        self.illustration.create_rectangle(4, 4, cw - 4, ch - 4, outline="#d9a2b8", width=1)
        return True

    def _draw_fallback_illustration(self, palette: dict[str, str]) -> None:
        c = self.illustration
        c.create_rectangle(4, 4, 256, 92, outline=palette["accent_dark"], width=1)
        c.create_oval(18, 16, 60, 44, fill=palette["accent"], outline="")
        c.create_oval(42, 12, 84, 44, fill=palette["accent"], outline="")
        c.create_oval(170, 18, 212, 44, fill=palette["accent"], outline="")
        c.create_oval(194, 14, 236, 42, fill=palette["accent"], outline="")
        c.create_oval(62, 42, 104, 78, fill="#f8e7ef", outline=palette["accent_dark"], width=1)
        c.create_oval(142, 42, 184, 78, fill="#f8e7ef", outline=palette["accent_dark"], width=1)
        c.create_polygon(72, 44, 82, 24, 92, 44, fill="#f2b7cf", outline=palette["accent_dark"])
        c.create_polygon(152, 44, 162, 24, 172, 44, fill="#f2b7cf", outline=palette["accent_dark"])
        c.create_oval(74, 56, 78, 60, fill=palette["text"], outline="")
        c.create_oval(86, 56, 90, 60, fill=palette["text"], outline="")
        c.create_oval(154, 56, 158, 60, fill=palette["text"], outline="")
        c.create_oval(166, 56, 170, 60, fill=palette["text"], outline="")
        c.create_arc(78, 62, 88, 68, start=200, extent=140, style="arc", outline=palette["text"], width=1)
        c.create_arc(158, 62, 168, 68, start=200, extent=140, style="arc", outline=palette["text"], width=1)
        c.create_text(24, 74, text="\u2661", fill=palette["accent_dark"], font=(self.ui_font, 12, "bold"))
        c.create_text(234, 72, text="\u2665", fill=palette["accent_dark"], font=(self.ui_font, 12, "bold"))
        c.create_text(126, 18, text="\u2726", fill=palette["accent_dark"], font=(self.ui_font, 11, "bold"))
        c.create_text(128, 84, text="Use My Image button to set your art", fill=palette["subtext"], font=(self.ui_font, 8))

    def on_pick_illustration(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select Illustration (PNG)",
            filetypes=[("PNG image", "*.png")],
        )
        if not selected:
            return

        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(selected, USER_ILLUST_PATH)
        except OSError:
            messagebox.showerror("Image", "Could not copy image file.")
            return

        self.settings["illustration_path"] = str(USER_ILLUST_PATH)
        self.settings["_loaded_path"] = ""
        save_gui_settings(self.settings)
        self._render_illustration(THEMES.get(self.current_theme.get(), THEMES["princess"]))
        self._append_assistant("Illustration updated.")

    def _on_illust_transform_change(self) -> None:
        self.settings["illust_scale"] = str(self.illust_scale.get())
        self.settings["illust_offset_x"] = str(self.illust_offset_x.get())
        self.settings["illust_offset_y"] = str(self.illust_offset_y.get())
        save_gui_settings(self.settings)
        self._render_illustration(THEMES.get(self.current_theme.get(), THEMES["princess"]))

    def on_apply_illust_size(self) -> None:
        self.illust_w.set(max(180, int(self.illust_w.get())))
        self.illust_h.set(max(80, int(self.illust_h.get())))
        self.settings["illust_w"] = str(self.illust_w.get())
        self.settings["illust_h"] = str(self.illust_h.get())
        save_gui_settings(self.settings)
        self._render_illustration(THEMES.get(self.current_theme.get(), THEMES["princess"]))

    def on_reset_illust_transform(self) -> None:
        self.illust_scale.set(100)
        self.illust_offset_x.set(0)
        self.illust_offset_y.set(0)
        self._on_illust_transform_change()

    def _switch_view(self, view_name: str) -> None:
        self.active_view = view_name
        self.view_frames[view_name].tkraise()
        self._update_tab_styles()

    def _update_tab_styles(self) -> None:
        self.tab_all_btn.configure(style="TabActive.TButton" if self.active_view == "all" else "Tab.TButton")
        self.tab_today_btn.configure(style="TabActive.TButton" if self.active_view == "today" else "Tab.TButton")
        self.tab_week_btn.configure(style="TabActive.TButton" if self.active_view == "week" else "Tab.TButton")

    def _configure_priority_tags(self) -> None:
        palette = THEMES.get(self.current_theme.get(), THEMES["princess"])
        colors = {
            "exam": "#b8325b",
            "interview": "#8f4db3",
            "study": "#267a63",
            "normal": palette["text"],
        }
        if self.current_theme.get() == "simple":
            colors = {"exam": "#7f1d1d", "interview": "#5b3d8f", "study": "#1d6b54", "normal": "#2f2f2f"}

        for tree in (self.tree_all, self.tree_today):
            for key, color in colors.items():
                tree.tag_configure(f"prio_{key}", foreground=color)
        for key, color in colors.items():
            self.tree_week.tag_configure(f"week_{key}", foreground=color)

    @staticmethod
    def _priority_for_title(title: str) -> str:
        lowered = title.lower()
        if (K_EXAM in title) or (K_CODE_TEST in title) or ("exam" in lowered) or ("test" in lowered):
            return "exam"
        if (K_INTERVIEW in title) or ("interview" in lowered):
            return "interview"
        if (K_STUDY in title) or ("study" in lowered):
            return "study"
        return "normal"

    @staticmethod
    def _weekday_sticker(d: date) -> str:
        if d.weekday() == 5:
            return "\u2661"  # Sat
        if d.weekday() == 6:
            return "\u2665"  # Sun
        return "\u273F"  # Weekday

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

        label = {"schedule": "Added schedule", "study_plan": "Created study plan", "exam_plan": "Created exam countdown plan"}.get(
            kind, "Saved"
        )
        self._append_assistant(f"{label}: {len(events)} event(s).")
        for line in format_events(events[:6]):
            self._append_assistant(line)
        if len(events) > 6:
            self._append_assistant(f"... and {len(events) - 6} more")

        self.refresh_events()

    def refresh_events(self) -> None:
        for tree in (self.tree_all, self.tree_today, self.tree_week):
            for row in tree.get_children():
                tree.delete(row)

        rows = list_events()
        today = datetime.now().date()
        by_day: dict[date, list[tuple[str, str]]] = {today + timedelta(days=i): [] for i in range(7)}

        for event_id, title, event_time, notified in rows:
            dt = datetime.fromisoformat(event_time)
            state = "notified" if notified else "pending"
            prio = self._priority_for_title(title)
            self.tree_all.insert(
                "",
                "end",
                values=(event_id, dt.strftime("%Y-%m-%d %H:%M"), title, state),
                tags=(f"prio_{prio}",),
            )
            if dt.date() == today:
                self.tree_today.insert(
                    "",
                    "end",
                    values=(event_id, dt.strftime("%H:%M"), title, state),
                    tags=(f"prio_{prio}",),
                )
            if dt.date() in by_day:
                by_day[dt.date()].append((f"{dt:%H:%M} {title}", prio))

        for i in range(7):
            d = today + timedelta(days=i)
            day_items = by_day[d]
            summary = " | ".join(item for item, _ in day_items[:4])
            if len(day_items) > 4:
                summary += f" | ... +{len(day_items) - 4}"
            dominant = "normal"
            if day_items:
                dominant = max((prio for _, prio in day_items), key=lambda p: PRIORITY_ORDER[p])
            self.tree_week.insert(
                "",
                "end",
                values=(self._weekday_sticker(d), d.strftime("%a"), d.strftime("%Y-%m-%d"), len(day_items), summary),
                tags=(f"week_{dominant}",),
            )

    def delete_selected(self) -> None:
        if self.active_view == "all":
            tree = self.tree_all
        elif self.active_view == "today":
            tree = self.tree_today
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
        should_clear = messagebox.askyesno("Reset", "Reset memory and clear all events + chat log?")
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

    saved_theme = app.settings.get("theme")
    if saved_theme in THEMES:
        app.current_theme.set(saved_theme)
        app._apply_theme(saved_theme)

    def on_close() -> None:
        if app.notifier_thread is not None and app.notifier_thread.is_alive():
            app.notifier_stop.set()
        save_chat_memory(app.memory)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()

from __future__ import annotations

import queue
import threading
from dataclasses import replace
from pathlib import Path

import click

from .calendar_sources import get_calendar_source
from .config import Config, load_config
from .models import Event
from .pipeline import run_pipeline
from .volumes import missing_volume

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk

    _TK_IMPORT_ERROR: Exception | None = None
except ImportError as exc:  # pragma: no cover - depends on the Python install
    _TK_IMPORT_ERROR = exc

_DONE = object()


class OrganizerApp:
    def __init__(self, root: tk.Tk, config: Config, config_path: str) -> None:
        self.root = root
        self.config = config
        self.log_queue: queue.Queue[object] = queue.Queue()
        self.calendar_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event: threading.Event | None = None

        root.title("Files Organizer")
        root.geometry("760x600")
        root.minsize(600, 460)

        self.config_path_var = tk.StringVar(value=config_path)
        self.input_var = tk.StringVar(value=str(config.input_dir))
        self.output_var = tk.StringVar(value=str(config.output_dir) if config.output_dir else "")
        self.mode_var = tk.StringVar(value=config.mode)
        self.margin_var = tk.StringVar(value=str(config.margin_hours))
        self.dry_run_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Gotowy.")

        self._build_widgets()
        self._poll_log_queue()
        self._poll_calendar_queue()
        self._load_calendar_preview()

    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 4}

        config_frame = ttk.LabelFrame(self.root, text="Konfiguracja")
        config_frame.pack(fill="x", **pad)
        config_frame.columnconfigure(1, weight=1)

        ttk.Label(config_frame, text="Plik config.yaml:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(config_frame, textvariable=self.config_path_var).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(config_frame, text="Wybierz…", command=self._browse_config_file).grid(row=0, column=2, padx=4)
        ttk.Button(config_frame, text="Wczytaj", command=self._load_config).grid(row=0, column=3, padx=(0, 8))

        paths_frame = ttk.LabelFrame(self.root, text="Ścieżki")
        paths_frame.pack(fill="x", **pad)
        paths_frame.columnconfigure(1, weight=1)
        self._path_row(paths_frame, "Katalog źródłowy:", self.input_var, 0)
        self._path_row(paths_frame, "Katalog docelowy:", self.output_var, 1)

        options_frame = ttk.LabelFrame(self.root, text="Ustawienia")
        options_frame.pack(fill="x", **pad)

        ttk.Label(options_frame, text="Tryb:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Radiobutton(options_frame, text="Kopiuj", value="copy", variable=self.mode_var).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(options_frame, text="Przenieś", value="move", variable=self.mode_var).grid(row=0, column=2, sticky="w")

        ttk.Label(options_frame, text="Margines dopasowania (h):").grid(row=0, column=3, sticky="w", **pad)
        ttk.Entry(options_frame, textvariable=self.margin_var, width=6).grid(row=0, column=4, sticky="w")

        ttk.Checkbutton(options_frame, text="Tylko podgląd (dry-run)", variable=self.dry_run_var).grid(
            row=0, column=5, sticky="w", **pad
        )

        actions_frame = ttk.Frame(self.root)
        actions_frame.pack(side="bottom", fill="x", **pad)
        ttk.Label(actions_frame, textvariable=self.status_var).pack(side="left")
        self.run_button = ttk.Button(actions_frame, text="Uruchom", command=self._on_run)
        self.run_button.pack(side="right")
        self.stop_button = ttk.Button(actions_frame, text="Zatrzymaj", command=self._on_stop, state="disabled")
        self.stop_button.pack(side="right", padx=(0, 8))

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, **pad)

        log_frame = ttk.Frame(notebook)
        notebook.add(log_frame, text="Log")
        self.log_widget = scrolledtext.ScrolledText(log_frame, state="disabled", height=18, wrap="none")
        self.log_widget.pack(fill="both", expand=True)

        calendar_frame = ttk.Frame(notebook)
        notebook.add(calendar_frame, text="Kalendarz")
        self._build_calendar_tab(calendar_frame)

    def _build_calendar_tab(self, parent: ttk.Frame) -> None:
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x", padx=4, pady=4)
        self.calendar_status_var = tk.StringVar(value="Brak wczytanego kalendarza.")
        ttk.Label(toolbar, textvariable=self.calendar_status_var).pack(side="left")
        self.calendar_refresh_button = ttk.Button(toolbar, text="Odśwież", command=self._load_calendar_preview)
        self.calendar_refresh_button.pack(side="right")

        columns = ("name", "start", "end", "location", "tag")
        headings = {"name": "Nazwa", "start": "Start", "end": "Koniec", "location": "Lokalizacja", "tag": "Tag"}
        widths = {"name": 200, "start": 130, "end": 130, "location": 140, "tag": 100}

        self.calendar_tree = ttk.Treeview(parent, columns=columns, show="headings", height=12)
        for col in columns:
            self.calendar_tree.heading(col, text=headings[col])
            self.calendar_tree.column(col, width=widths[col], anchor="w")

        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.calendar_tree.yview)
        self.calendar_tree.configure(yscrollcommand=scrollbar.set)
        self.calendar_tree.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=(0, 4))
        scrollbar.pack(side="right", fill="y", pady=(0, 4))

    def _path_row(self, parent: ttk.LabelFrame, label: str, var: tk.StringVar, row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=4)
        ttk.Button(parent, text="Wybierz…", command=lambda: self._browse_dir(var)).grid(row=row, column=2, padx=8)

    def _browse_dir(self, var: tk.StringVar) -> None:
        chosen = filedialog.askdirectory(initialdir=var.get() or None)
        if chosen:
            var.set(chosen)

    def _browse_config_file(self) -> None:
        initial = Path(self.config_path_var.get())
        chosen = filedialog.askopenfilename(
            initialdir=str(initial.parent) if initial.parent.exists() else None,
            filetypes=[("YAML", "*.yaml *.yml"), ("Wszystkie pliki", "*.*")],
        )
        if chosen:
            self.config_path_var.set(chosen)

    def _load_config(self) -> None:
        path = self.config_path_var.get().strip()
        if not path:
            return
        try:
            config = load_config(path)
        except Exception as exc:
            messagebox.showerror("Błąd wczytywania configu", str(exc))
            return

        self.config = config
        self.input_var.set(str(config.input_dir))
        self.output_var.set(str(config.output_dir) if config.output_dir else "")
        self.mode_var.set(config.mode)
        self.margin_var.set(str(config.margin_hours))
        self._append_log(f"Wczytano konfigurację: {path}")
        self._load_calendar_preview()

    def _load_calendar_preview(self) -> None:
        calendar_config = self.config.calendar
        self._clear_calendar_tree()

        if not calendar_config:
            self.calendar_status_var.set("Konfiguracja nie zawiera kalendarza.")
            return

        self.calendar_status_var.set("Wczytywanie kalendarza…")
        self.calendar_refresh_button.configure(state="disabled")
        threading.Thread(target=self._fetch_calendar_events, args=(calendar_config,), daemon=True).start()

    def _fetch_calendar_events(self, calendar_config: dict) -> None:
        # Tkinter widgets may only be touched from the main thread, so results go
        # through the same queue + polling pattern as the pipeline log (see _poll_log_queue).
        try:
            events = get_calendar_source(calendar_config).get_events()
        except Exception as exc:
            self.calendar_queue.put(("error", str(exc)))
            return
        self.calendar_queue.put(("loaded", events))

    def _poll_calendar_queue(self) -> None:
        try:
            while True:
                kind, payload = self.calendar_queue.get_nowait()
                if kind == "loaded":
                    self._on_calendar_loaded(payload)
                else:
                    self._on_calendar_error(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_calendar_queue)

    def _on_calendar_loaded(self, events: list[Event]) -> None:
        for event in sorted(events, key=lambda e: e.start):
            self.calendar_tree.insert(
                "",
                "end",
                values=(
                    event.name,
                    f"{event.start:%Y-%m-%d %H:%M}",
                    f"{event.end:%Y-%m-%d %H:%M}",
                    event.location or "",
                    event.tag or "",
                ),
            )
        self.calendar_status_var.set(f"Wczytano {len(events)} wydarzeń.")
        self.calendar_refresh_button.configure(state="normal")

    def _on_calendar_error(self, message: str) -> None:
        self.calendar_status_var.set(f"Błąd wczytywania kalendarza: {message}")
        self.calendar_refresh_button.configure(state="normal")

    def _clear_calendar_tree(self) -> None:
        for item in self.calendar_tree.get_children():
            self.calendar_tree.delete(item)

    def _append_log(self, message: str) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", message + "\n")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _poll_log_queue(self) -> None:
        try:
            while True:
                message = self.log_queue.get_nowait()
                if message is _DONE:
                    self.run_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.status_var.set("Gotowy.")
                elif isinstance(message, str) and message.startswith("ERROR:"):
                    messagebox.showerror("Błąd", message[len("ERROR:") :])
                    self._append_log(message)
                else:
                    self._append_log(str(message))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)

    def _on_run(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            return

        try:
            margin_hours = float(self.margin_var.get())
        except ValueError:
            messagebox.showerror("Błąd", "Margines musi być liczbą.")
            return

        input_dir = Path(self.input_var.get())
        output_dir_raw = self.output_var.get().strip()
        if not output_dir_raw:
            messagebox.showerror("Błąd", "Wybierz katalog docelowy.")
            return
        output_dir = Path(output_dir_raw)

        for path, label in ((input_dir, "wejściowy"), (output_dir, "wyjściowy")):
            volume = missing_volume(path)
            if volume is not None:
                messagebox.showerror(
                    "Błąd", f"Katalog {label} ({path}) jest na dysku, który nie jest podłączony: {volume} nie istnieje."
                )
                return

        run_config = replace(
            self.config,
            input_dir=input_dir,
            output_dir=output_dir,
            mode=self.mode_var.get(),
            margin_hours=margin_hours,
        )
        dry_run = self.dry_run_var.get()

        self.log_widget.configure(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.configure(state="disabled")

        self.run_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_var.set("Trwa podgląd…" if dry_run else "Trwa kopiowanie/przenoszenie…")
        self.stop_event = threading.Event()
        self.worker = threading.Thread(
            target=self._run_worker, args=(run_config, dry_run, self.stop_event), daemon=True
        )
        self.worker.start()

    def _on_stop(self) -> None:
        if self.stop_event is None:
            return
        self.stop_event.set()
        self.stop_button.configure(state="disabled")
        self.status_var.set("Zatrzymywanie… (bieżący plik zostanie dokończony)")

    def _run_worker(self, run_config: Config, dry_run: bool, stop_event: threading.Event) -> None:
        try:
            run_pipeline(run_config, dry_run, log=self.log_queue.put, stop_event=stop_event)
            if stop_event.is_set():
                self.log_queue.put("Zatrzymano na życzenie użytkownika.")
            else:
                self.log_queue.put("Podgląd zakończony." if dry_run else "Zakończono.")
        except Exception as exc:
            self.log_queue.put(f"ERROR:{exc}")
        finally:
            self.log_queue.put(_DONE)


def launch_app(config: Config, config_path: str = "config.yaml") -> None:
    """Open the GUI window: pick/edit paths, set mode and config, run the action, watch the log."""
    if _TK_IMPORT_ERROR is not None:
        raise click.UsageError(
            "Tkinter jest niedostępne w tym środowisku Pythona "
            f"({_TK_IMPORT_ERROR}). Na macOS z Homebrew zainstaluj obsługę Tk, np.: "
            "`brew install python-tk@3.12` (dopasuj wersję do swojego Pythona), "
            "a następnie utwórz środowisko wirtualne od nowa."
        )
    root = tk.Tk()
    OrganizerApp(root, config, config_path)
    root.mainloop()

from __future__ import annotations

import queue
import threading
from pathlib import Path

import click

from .config import Config
from .exif_reader import IMAGE_SUFFIXES
from .face_recognizers import get_face_recognizer
from .face_watcher import watch_for_faces

try:
    import tkinter as tk
    from tkinter import scrolledtext, ttk

    _TK_IMPORT_ERROR: Exception | None = None
except ImportError as exc:  # pragma: no cover - depends on the Python install
    _TK_IMPORT_ERROR = exc

try:
    from PIL import Image, ImageTk

    _PIL_IMPORT_ERROR: Exception | None = None
except ImportError as exc:  # pragma: no cover - depends on the Python install
    _PIL_IMPORT_ERROR = exc

_PREVIEW_MAX_SIZE = (640, 640)


class _ConfirmRequest:
    def __init__(self, path: Path, names: list[str]) -> None:
        self.path = path
        self.names = names
        self.approved = False
        self.done = threading.Event()


class FaceWatcherApp:
    """Tk window for the `--gui` mode of `files-organizer-faces`.

    The face watcher itself keeps running on its own background thread (see
    `watch_for_faces`); this class only adds a Tk front end around it. When confirmation is
    required, `_request_confirmation` (called from the watcher's worker thread) blocks that
    thread on a `threading.Event` while it hands the request to the main thread via a queue -
    Tk widgets may only be touched from the thread running `mainloop`, so the actual dialog is
    built by `_poll_confirm_queue` instead of directly by the caller.
    """

    def __init__(self, root: tk.Tk, config: Config, auto: bool, dry_run: bool) -> None:
        self.root = root
        self.config = config
        self.auto = auto
        self.dry_run = dry_run
        self.log_queue: queue.Queue[object] = queue.Queue()
        self.confirm_queue: queue.Queue[_ConfirmRequest] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self._dialog_open = False

        root.title("Files Organizer — rozpoznawanie twarzy")
        root.geometry("640x420")
        root.minsize(480, 320)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        mode_notes = []
        if dry_run:
            mode_notes.append("dry-run")
        mode_notes.append("automatycznie" if auto else "z potwierdzeniem")
        mode_note = f" ({', '.join(mode_notes)})"

        self.status_var = tk.StringVar(value=f"Obserwuję {config.input_dir}{mode_note}")
        ttk.Label(root, textvariable=self.status_var).pack(fill="x", padx=8, pady=(8, 0))

        self.log_widget = scrolledtext.ScrolledText(root, state="disabled", wrap="word")
        self.log_widget.pack(fill="both", expand=True, padx=8, pady=8)

        self._start_watcher()
        self._poll_log_queue()
        self._poll_confirm_queue()

    def _start_watcher(self) -> None:
        recognizer = get_face_recognizer(self.config.face_recognition)
        confirm_fn = None if self.auto else self._request_confirmation
        self.worker = threading.Thread(
            target=watch_for_faces,
            args=(self.config.input_dir, recognizer, self.log_queue.put, self.stop_event),
            kwargs={"dry_run": self.dry_run, "confirm_fn": confirm_fn},
            daemon=True,
        )
        self.worker.start()

    def _request_confirmation(self, path: Path, names: list[str]) -> bool:
        request = _ConfirmRequest(path, names)
        self.confirm_queue.put(request)
        request.done.wait()
        return request.approved

    def _poll_confirm_queue(self) -> None:
        if not self._dialog_open:
            try:
                request = self.confirm_queue.get_nowait()
            except queue.Empty:
                pass
            else:
                self._show_confirm_dialog(request)
        self.root.after(150, self._poll_confirm_queue)

    def _show_confirm_dialog(self, request: _ConfirmRequest) -> None:
        self._dialog_open = True
        dialog = tk.Toplevel(self.root)
        dialog.title("Potwierdź tag")
        dialog.transient(self.root)
        dialog.grab_set()

        preview = self._load_preview(request.path)
        if preview is not None:
            image_label = ttk.Label(dialog, image=preview)
            image_label.image = preview  # keep a reference - Tk drops the image otherwise
            image_label.pack(padx=8, pady=8)
        else:
            ttk.Label(dialog, text="(brak podglądu)").pack(padx=8, pady=8)

        ttk.Label(dialog, text=str(request.path)).pack(padx=8)
        ttk.Label(dialog, text=f"Rozpoznano: {', '.join(request.names)}", font=("TkDefaultFont", 11, "bold")).pack(
            padx=8, pady=(0, 8)
        )

        buttons = ttk.Frame(dialog)
        buttons.pack(pady=(0, 8))

        def resolve(approved: bool) -> None:
            request.approved = approved
            request.done.set()
            self._dialog_open = False
            dialog.destroy()

        ttk.Button(buttons, text="Zatwierdź", command=lambda: resolve(True)).pack(side="left", padx=4)
        ttk.Button(buttons, text="Odrzuć", command=lambda: resolve(False)).pack(side="left", padx=4)
        dialog.protocol("WM_DELETE_WINDOW", lambda: resolve(False))

    def _load_preview(self, path: Path):
        if _PIL_IMPORT_ERROR is not None or path.suffix.lower() not in IMAGE_SUFFIXES:
            return None
        try:
            image = Image.open(path)
            image.thumbnail(_PREVIEW_MAX_SIZE)
            return ImageTk.PhotoImage(image)
        except Exception:
            return None

    def _append_log(self, message: str) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", message + "\n")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _poll_log_queue(self) -> None:
        try:
            while True:
                message = self.log_queue.get_nowait()
                self._append_log(str(message))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)

    def _on_close(self) -> None:
        self.stop_event.set()
        self.root.destroy()


def launch_face_app(config: Config, auto: bool = False, dry_run: bool = False) -> None:
    """Open a GUI window that previews each recognized photo before its tag is confirmed."""
    if _TK_IMPORT_ERROR is not None:
        raise click.UsageError(
            "Tkinter jest niedostępne w tym środowisku Pythona "
            f"({_TK_IMPORT_ERROR}). Na macOS z Homebrew zainstaluj obsługę Tk, np.: "
            "`brew install python-tk@3.12` (dopasuj wersję do swojego Pythona), "
            "a następnie utwórz środowisko wirtualne od nowa."
        )
    root = tk.Tk()
    FaceWatcherApp(root, config, auto=auto, dry_run=dry_run)
    root.mainloop()

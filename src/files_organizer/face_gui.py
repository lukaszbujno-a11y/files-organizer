from __future__ import annotations

import queue
import signal
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
        self._pending_request: _ConfirmRequest | None = None

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
        if self.stop_event.is_set():
            return  # window is on its way down (see request_shutdown) - stop rescheduling
        if not self._dialog_open:
            try:
                request = self.confirm_queue.get_nowait()
            except queue.Empty:
                pass
            else:
                self._show_confirm_dialog(request)
        self.root.after(150, self._poll_confirm_queue)

    def _show_confirm_dialog(self, request: _ConfirmRequest) -> None:
        # Ctrl+C can land here mid-construction, right as request_shutdown() tears the window
        # down from a reentrant signal handler call - harmless once it happens, so just bail.
        try:
            self._build_confirm_dialog(request)
        except tk.TclError:
            pass

    def _build_confirm_dialog(self, request: _ConfirmRequest) -> None:
        self._dialog_open = True
        self._pending_request = request
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
            self._pending_request = None
            dialog.destroy()

        approve_button = ttk.Button(buttons, text="Zatwierdź", command=lambda: resolve(True))
        approve_button.pack(side="left", padx=4)
        ttk.Button(buttons, text="Odrzuć", command=lambda: resolve(False)).pack(side="left", padx=4)
        dialog.protocol("WM_DELETE_WINDOW", lambda: resolve(False))

        # Enter/Return confirms, Escape rejects, regardless of which widget has focus.
        dialog.bind("<Return>", lambda event: resolve(True))
        dialog.bind("<KP_Enter>", lambda event: resolve(True))
        dialog.bind("<Escape>", lambda event: resolve(False))
        # focus_set() alone only records which widget *would* get keyboard input once the
        # window itself has focus; focus_force() also grabs window-level focus from the OS/WM,
        # so Enter confirms immediately without the user having to click the dialog first.
        approve_button.focus_force()

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
        self.request_shutdown()

    def request_shutdown(self, *_args) -> None:
        """Stop the watcher and close the window - shared by the window-close button and Ctrl+C.

        A pending confirm dialog is resolved as rejected rather than left open: the worker
        thread would otherwise block forever on `request.done.wait()` for a dialog that's
        about to be destroyed, since nothing else will ever set that event.
        """
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        if self._pending_request is not None and not self._pending_request.done.is_set():
            self._pending_request.approved = False
            self._pending_request.done.set()
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
    app = FaceWatcherApp(root, config, auto=auto, dry_run=dry_run)

    # Tkinter's mainloop only checks for pending signals while a Python callback (like our
    # `after`-scheduled polling) is actually running - the rest of the time it's blocked in a
    # C-level Tcl event wait that never returns control to the interpreter. With the *default*
    # SIGINT handler that's what made Ctrl+C so unreliable here: the KeyboardInterrupt it raises
    # gets caught and silently reported by Tkinter's own callback-exception handler instead of
    # propagating, so mainloop just keeps going. Installing our own handler sidesteps that: it
    # runs to completion instead of raising, so there's nothing left for Tkinter to swallow.
    signal.signal(signal.SIGINT, lambda signum, frame: app.request_shutdown())

    root.mainloop()

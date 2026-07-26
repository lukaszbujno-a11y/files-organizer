from __future__ import annotations

import queue
import signal
import threading
from pathlib import Path
from typing import Callable

import click

from .config import Config
from .exif_reader import IMAGE_SUFFIXES
from .face_recognizers import get_face_recognizer
from .face_watcher import FaceDetection, scan_for_faces, watch_for_faces
from .metadata import write_tags

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


def _load_preview(path: Path):
    if _PIL_IMPORT_ERROR is not None or path.suffix.lower() not in IMAGE_SUFFIXES:
        return None
    try:
        image = Image.open(path)
        image.thumbnail(_PREVIEW_MAX_SIZE)
        return ImageTk.PhotoImage(image)
    except Exception:
        return None


def _build_tag_dialog(parent: tk.Misc, path: Path, names: list[str], title: str, on_resolve: Callable[[bool], None]):
    """Build a "Zatwierdź / Odrzuć" popup for one photo's recognized names.

    Shared by the live per-photo confirm flow and the after-scan batch review - both just
    need a preview, the recognized names, and a way to react to the user's choice, they
    differ only in what `on_resolve` does with it (unblock a waiting worker thread vs.
    record the choice and move on to the next photo in the batch).
    """
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.grab_set()

    preview = _load_preview(path)
    if preview is not None:
        image_label = ttk.Label(dialog, image=preview)
        image_label.image = preview  # keep a reference - Tk drops the image otherwise
        image_label.pack(padx=8, pady=8)
    else:
        ttk.Label(dialog, text="(brak podglądu)").pack(padx=8, pady=8)

    ttk.Label(dialog, text=str(path)).pack(padx=8)
    ttk.Label(dialog, text=f"Rozpoznano: {', '.join(names)}", font=("TkDefaultFont", 11, "bold")).pack(
        padx=8, pady=(0, 8)
    )

    buttons = ttk.Frame(dialog)
    buttons.pack(pady=(0, 8))

    def resolve(approved: bool) -> None:
        dialog.destroy()
        on_resolve(approved)

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
    return dialog


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

        def resolve(approved: bool) -> None:
            request.approved = approved
            request.done.set()
            self._dialog_open = False
            self._pending_request = None

        _build_tag_dialog(self.root, request.path, request.names, "Potwierdź tag", resolve)

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


def _require_tk() -> None:
    if _TK_IMPORT_ERROR is not None:
        raise click.UsageError(
            "Tkinter jest niedostępne w tym środowisku Pythona "
            f"({_TK_IMPORT_ERROR}). Na macOS z Homebrew zainstaluj obsługę Tk, np.: "
            "`brew install python-tk@3.12` (dopasuj wersję do swojego Pythona), "
            "a następnie utwórz środowisko wirtualne od nowa."
        )


def launch_face_app(config: Config, auto: bool = False, dry_run: bool = False) -> None:
    """Open a GUI window that previews each recognized photo before its tag is confirmed."""
    _require_tk()
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


class FaceScanReviewApp:
    """Tk window for the `--scan --gui` mode of `files-organizer-faces`.

    Unlike `FaceWatcherApp`, recognition never blocks on user input here: `scan_for_faces`
    runs straight through the whole directory on a worker thread first (see `_run_scan`), and
    only once that's fully done does review start - one popup per photo (`_show_next_review_dialog`),
    followed by a per-person summary (`_show_summary`) of what got approved. Tags are written
    only after the user confirms that summary, never while scanning or reviewing is still going.
    """

    def __init__(self, root: tk.Tk, config: Config, dry_run: bool, auto: bool = False, limit: int | None = None) -> None:
        self.root = root
        self.config = config
        self.dry_run = dry_run
        self.auto = auto
        self.limit = limit
        self.log_queue: queue.Queue[object] = queue.Queue()
        self.scan_result_queue: queue.Queue[list[FaceDetection]] = queue.Queue()
        self.write_done_queue: queue.Queue[bool] = queue.Queue()
        self._review_queue: list[FaceDetection] = []
        self._total = 0
        self._approved: list[FaceDetection] = []
        self._rejected: list[FaceDetection] = []
        self._closed = False

        root.title("Files Organizer — przegląd rozpoznanych twarzy")
        root.geometry("640x420")
        root.minsize(480, 320)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        mode_note = " (dry-run)" if dry_run else ""
        self.status_var = tk.StringVar(value=f"Skanuję {config.input_dir}{mode_note}…")
        ttk.Label(root, textvariable=self.status_var).pack(fill="x", padx=8, pady=(8, 0))

        self.log_widget = scrolledtext.ScrolledText(root, state="disabled", wrap="word")
        self.log_widget.pack(fill="both", expand=True, padx=8, pady=8)

        self._start_scan()
        self._poll_log_queue()
        self._poll_scan_result()

    def _start_scan(self) -> None:
        recognizer = get_face_recognizer(self.config.face_recognition)
        threading.Thread(target=self._run_scan, args=(recognizer,), daemon=True).start()

    def _run_scan(self, recognizer) -> None:
        detections = scan_for_faces(self.config.input_dir, recognizer, self.log_queue.put, limit=self.limit)
        self.scan_result_queue.put(detections)

    def _poll_scan_result(self) -> None:
        if self._closed:
            return
        try:
            detections = self.scan_result_queue.get_nowait()
        except queue.Empty:
            self.root.after(150, self._poll_scan_result)
            return
        self._begin_review(detections)

    def _begin_review(self, detections: list[FaceDetection]) -> None:
        if not detections:
            self.status_var.set(f"Skanowanie zakończone — nie rozpoznano nikogo w {self.config.input_dir}")
            return
        if self.auto:
            self.status_var.set(f"Skanowanie zakończone — tagowanie automatyczne {len(detections)} zdjęć")
            self._approved = list(detections)
            self._write_approved()
            return
        self.status_var.set(f"Skanowanie zakończone — do przejrzenia: {len(detections)}")
        self._total = len(detections)
        self._review_queue = list(detections)
        self._show_next_review_dialog()

    def _show_next_review_dialog(self) -> None:
        if self._closed:
            return
        if not self._review_queue:
            self._show_summary()
            return
        detection = self._review_queue.pop(0)
        index = self._total - len(self._review_queue)
        title = f"Potwierdź tag ({index}/{self._total})"

        def resolve(approved: bool) -> None:
            (self._approved if approved else self._rejected).append(detection)
            self._show_next_review_dialog()

        try:
            _build_tag_dialog(self.root, detection.path, detection.names, title, resolve)
        except tk.TclError:
            pass  # window closed mid-dialog (e.g. Ctrl+C) - nothing left to review into

    def _show_summary(self) -> None:
        if self._closed:
            return
        self.status_var.set("Przegląd zakończony")

        counts: dict[str, list[int]] = {}
        for detection in self._approved:
            for name in detection.names:
                counts.setdefault(name, [0, 0])[0] += 1
        for detection in self._approved + self._rejected:
            for name in detection.names:
                counts.setdefault(name, [0, 0])[1] += 1

        dialog = tk.Toplevel(self.root)
        dialog.title("Podsumowanie")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="Zatwierdzone tagi per osoba:", font=("TkDefaultFont", 11, "bold")).pack(
            padx=12, pady=(12, 4), anchor="w"
        )
        if counts:
            for name in sorted(counts):
                approved_count, total = counts[name]
                ttk.Label(dialog, text=f"{name}: {approved_count}/{total} zdjęć zatwierdzonych").pack(
                    padx=12, anchor="w"
                )
        else:
            ttk.Label(dialog, text="(brak zatwierdzonych tagów)").pack(padx=12, anchor="w")

        buttons = ttk.Frame(dialog)
        buttons.pack(pady=12)

        def finish() -> None:
            dialog.destroy()
            self._write_approved()

        def cancel() -> None:
            dialog.destroy()
            self.status_var.set("Przegląd anulowany — nie zapisano żadnych tagów")

        # WM_DELETE_WINDOW (the window's own X button) must go to cancel, not finish - a user
        # closing the window is telling us to abandon the review, not confirm it. Wiring it to
        # finish() used to write every approved tag as a side effect of just closing the window.
        button_label = "Zamknij" if self.dry_run else "Zapisz tagi"
        ttk.Button(buttons, text=button_label, command=finish).pack(side="left", padx=4)
        ttk.Button(buttons, text="Anuluj", command=cancel).pack(side="left", padx=4)
        dialog.protocol("WM_DELETE_WINDOW", cancel)

    def _write_approved(self) -> None:
        self.status_var.set("Zapisywanie tagów…")
        threading.Thread(target=self._run_write, daemon=True).start()
        self._poll_write_done()

    def _run_write(self) -> None:
        for detection in self._approved:
            if self.dry_run:
                self.log_queue.put(f"{detection.path} -> (dry-run) oznaczono by tagiem: {', '.join(detection.names)}")
            else:
                write_tags(detection.path, detection.names)
                self.log_queue.put(f"{detection.path} -> {', '.join(detection.names)}")
        for detection in self._rejected:
            self.log_queue.put(f"{detection.path} -> pominięto na żądanie użytkownika: {', '.join(detection.names)}")
        if self.dry_run:
            self.log_queue.put(f"Dry-run zakończony — oznaczono by {len(self._approved)} zdjęć.")
        else:
            self.log_queue.put(f"Zakończono dodawanie tagów — oznaczono {len(self._approved)} zdjęć.")
        self.write_done_queue.put(True)

    def _poll_write_done(self) -> None:
        if self._closed:
            return
        try:
            self.write_done_queue.get_nowait()
        except queue.Empty:
            self.root.after(150, self._poll_write_done)
            return
        summary = "Dry-run zakończony" if self.dry_run else f"Gotowe — zapisano tagi dla {len(self._approved)} zdjęć"
        self.status_var.set(summary)

    def _append_log(self, message: str) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", message + "\n")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _poll_log_queue(self) -> None:
        if self._closed:
            return
        try:
            while True:
                message = self.log_queue.get_nowait()
                self._append_log(str(message))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)

    def _on_close(self, *_args) -> None:
        self._closed = True
        self.root.destroy()


def launch_face_scan_app(config: Config, dry_run: bool = False, auto: bool = False, limit: int | None = None) -> None:
    """Open a GUI window that scans `input_dir` once, then reviews every detection at the end.

    Unlike `launch_face_app`, this doesn't keep watching `input_dir` afterwards - it's a
    one-shot pass meant for reviewing a whole batch of photos without having to sit through a
    confirmation popup for each one as it's being recognized. `limit`, when given, stops the
    scan after that many detections instead of always going through the whole directory.
    """
    _require_tk()
    root = tk.Tk()
    app = FaceScanReviewApp(root, config, dry_run=dry_run, auto=auto, limit=limit)
    signal.signal(signal.SIGINT, lambda signum, frame: app._on_close())
    root.mainloop()

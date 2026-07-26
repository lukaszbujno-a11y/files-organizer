from __future__ import annotations

import signal
import threading

import click

from .config import load_config
from .face_recognizers import get_face_recognizer
from .face_watcher import watch_for_faces
from .volumes import missing_volume


@click.command()
@click.option("--config", "config_path", default="config.yaml", show_default=True, help="Path to config YAML file.")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Pokaż, kogo rozpoznano i jaki tag zostałby dodany, bez faktycznego zapisu do pliku.",
)
@click.option(
    "--auto",
    is_flag=True,
    help="Taguj automatycznie, bez pytania o potwierdzenie każdego zdjęcia.",
)
@click.option(
    "--gui",
    is_flag=True,
    help="Otwórz okno graficzne z podglądem zdjęcia przy potwierdzaniu tagu (zamiast terminala).",
)
def main(config_path: str, dry_run: bool, auto: bool, gui: bool) -> None:
    """Run a long-lived background watcher that tags recognized faces on new photos.

    Independent of `files-organizer`: watches `input_dir` continuously and reacts to
    each new file as it appears, instead of processing a snapshot of the directory once.

    By default, every recognized tag must be confirmed before it's written - pass `--auto`
    to tag automatically instead.
    """
    config = load_config(config_path)
    if not config.face_recognition:
        raise click.UsageError(
            f"Sekcja 'face_recognition' nie jest ustawiona w {config_path}. Zobacz config.example.yaml."
        )

    volume = missing_volume(config.input_dir)
    if volume is not None:
        raise click.UsageError(f"Katalog wejściowy ({config.input_dir}) jest na dysku, który nie jest podłączony: {volume}.")

    if gui:
        from .face_gui import launch_face_app

        launch_face_app(config, auto=auto, dry_run=dry_run)
        return

    recognizer = get_face_recognizer(config.face_recognition)
    stop_event = threading.Event()

    def handle_sigint(signum, frame):
        stop_event.set()
        click.echo("\nZatrzymywanie obserwatora twarzy…")

    signal.signal(signal.SIGINT, handle_sigint)

    def confirm_tag(path, names: list[str]) -> bool:
        return click.confirm(f"{path} -> oznaczyć tagiem: {', '.join(names)}?", default=True)

    mode_notes = []
    if dry_run:
        mode_notes.append("dry-run: bez zapisu tagów")
    mode_notes.append("automatyczne tagowanie" if auto else "potwierdzanie każdego tagu")
    mode_note = f" [{', '.join(mode_notes)}]"

    click.echo(f"Obserwuję {config.input_dir} pod kątem znanych osób{mode_note} (Ctrl+C, aby zakończyć)…")
    watch_for_faces(
        config.input_dir,
        recognizer,
        log=click.echo,
        stop_event=stop_event,
        dry_run=dry_run,
        confirm_fn=None if auto else confirm_tag,
    )


if __name__ == "__main__":
    main()

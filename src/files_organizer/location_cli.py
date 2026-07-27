from __future__ import annotations

import signal
import threading

import click

from .config import load_config
from .exif_reader import iter_media_files
from .location_recognizers import get_location_recognizer
from .location_watcher import LocationDetection, scan_for_locations, watch_for_locations
from .metadata import read_tagged_locations, remove_location_tags, write_location_tags
from .volumes import missing_volume

# Value `scan` takes when `--scan` is passed with no number - "scan everything", as opposed
# to `--scan N` which caps the number of detections. Kept out of the non-negative range an
# actual limit would use.
_SCAN_NO_LIMIT = -1


@click.command()
@click.option("--config", "config_path", default="config.yaml", show_default=True, help="Path to config YAML file.")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Pokaż, jaka lokalizacja zostałaby otagowana, bez faktycznego zapisu do pliku.",
)
@click.option(
    "--auto",
    is_flag=True,
    help="Taguj automatycznie, bez pytania o potwierdzenie każdego zdjęcia.",
)
@click.option(
    "--scan",
    "scan",
    is_flag=False,
    flag_value=_SCAN_NO_LIMIT,
    default=None,
    type=int,
    metavar="[N]",
    help=(
        "Przeskanuj input_dir raz i zakończ, zamiast obserwować go w nieskończoność. "
        "Bez liczby: przeskanuj wszystkie zdjęcia. Z liczbą, np. --scan 100: przerwij "
        "skanowanie po znalezieniu pierwszych 100 wykryć. Rozpoznawanie idzie przez "
        "zdjęcia bez pytania, a potwierdzenie tagów następuje dopiero po zakończeniu "
        "całego skanu."
    ),
)
@click.option(
    "--untag-all",
    is_flag=True,
    help="Usuń wszystkie tagi Location:/Country: dodane wcześniej do zdjęć w input_dir i zakończ.",
)
def main(config_path: str, dry_run: bool, auto: bool, scan: int | None, untag_all: bool) -> None:
    """Run a long-lived background watcher that tags recognized locations on new photos.

    Independent of `files-organizer` and of `files-organizer-faces`: watches `input_dir`
    continuously and reacts to each new file as it appears, instead of processing a snapshot
    of the directory once.

    By default, every recognized tag must be confirmed before it's written - pass `--auto`
    to tag automatically instead. Pass `--scan` for a one-shot pass instead of continuous
    watching: recognition runs over every photo first, and confirmation only happens once
    the whole scan is done.
    """
    config = load_config(config_path)

    volume = missing_volume(config.input_dir)
    if volume is not None:
        raise click.UsageError(f"Katalog wejściowy ({config.input_dir}) jest na dysku, który nie jest podłączony: {volume}.")

    if untag_all:
        _run_untag_all(config.input_dir)
        return

    if not config.location_recognition:
        raise click.UsageError(
            f"Sekcja 'location_recognition' nie jest ustawiona w {config_path}. Zobacz config.example.yaml."
        )

    if scan is not None:
        scan_limit = None if scan == _SCAN_NO_LIMIT else scan
        _run_scan_cli(config, dry_run=dry_run, auto=auto, limit=scan_limit)
        return

    recognizer = get_location_recognizer(config.location_recognition)
    stop_event = threading.Event()

    def handle_sigint(signum, frame):
        stop_event.set()
        click.echo("\nZatrzymywanie obserwatora lokalizacji…")

    signal.signal(signal.SIGINT, handle_sigint)

    def confirm_tag(path, location) -> bool:
        return click.confirm(f"{path} -> oznaczyć tagiem: {location.city}, {location.country}?", default=True)

    mode_notes = []
    if dry_run:
        mode_notes.append("dry-run: bez zapisu tagów")
    mode_notes.append("automatyczne tagowanie" if auto else "potwierdzanie każdego tagu")
    mode_note = f" [{', '.join(mode_notes)}]"

    click.echo(f"Obserwuję {config.input_dir} pod kątem lokalizacji zdjęć{mode_note} (Ctrl+C, aby zakończyć)…")
    watch_for_locations(
        config.input_dir,
        recognizer,
        log=click.echo,
        stop_event=stop_event,
        dry_run=dry_run,
        confirm_fn=None if auto else confirm_tag,
    )


def _run_untag_all(input_dir) -> None:
    """Find every file under `input_dir` carrying a `Location:` tag and remove its tags."""
    tagged_paths = [path for path in iter_media_files(input_dir) if read_tagged_locations(path)]
    if not tagged_paths:
        click.echo("Nie znaleziono żadnych zdjęć z tagiem Location:.")
        return

    click.echo(f"Znaleziono {len(tagged_paths)} zdjęć z tagiem Location::")
    for path in tagged_paths:
        click.echo(f"  {path} -> {', '.join(read_tagged_locations(path))}")

    if not click.confirm(f"\nUsunąć tagi Location:/Country: z {len(tagged_paths)} zdjęć w {input_dir}?", default=False):
        click.echo("Przerwano, nic nie zmieniono.")
        return

    for path in tagged_paths:
        removed = remove_location_tags(path)
        click.echo(f"{path} -> usunięto: {', '.join(removed)}")


def _run_scan_cli(config, dry_run: bool, auto: bool, limit: int | None = None) -> None:
    recognizer = get_location_recognizer(config.location_recognition)
    click.echo(f"Skanuję {config.input_dir}…")
    detections = scan_for_locations(config.input_dir, recognizer, log=click.echo, limit=limit)
    if not detections:
        click.echo("Nie rozpoznano żadnej lokalizacji.")
        return

    if auto:
        approved: list[LocationDetection] = detections
    else:
        approved = [
            detection
            for detection in detections
            if click.confirm(
                f"{detection.path} -> oznaczyć tagiem: {detection.location.city}, {detection.location.country}?",
                default=True,
            )
        ]

    click.echo(f"Podsumowanie: {len(approved)}/{len(detections)} zatwierdzonych")

    for detection in approved:
        if dry_run:
            click.echo(
                f"{detection.path} -> (dry-run) oznaczono by tagiem: "
                f"{detection.location.city}, {detection.location.country}"
            )
        else:
            write_location_tags(detection.path, detection.location)
            click.echo(f"{detection.path} -> {detection.location.city}, {detection.location.country}")

    if dry_run:
        click.echo(f"Dry-run zakończony — oznaczono by {len(approved)} zdjęć.")
    else:
        click.echo(f"Zakończono dodawanie tagów — oznaczono {len(approved)} zdjęć.")


if __name__ == "__main__":
    main()

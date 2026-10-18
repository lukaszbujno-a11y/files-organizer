from __future__ import annotations

import signal
import threading
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import click

from .catalog import Catalog, CatalogEntry, CatalogQuery, open_catalog
from .config import Config, load_config
from .volumes import missing_volume

_config_option = click.option(
    "--config", "config_path", default="config.yaml", show_default=True, help="Path to config YAML file."
)


@click.group()
def main() -> None:
    """Lokalny katalog metadanych zdjęć (SQLite): skanowanie i wyszukiwanie."""


@main.command()
@_config_option
@click.option("--input-dir", "input_dir", type=click.Path(path_type=Path), default=None, help="Nadpisz input_dir z configu.")
def scan(config_path: str, input_dir: Path | None) -> None:
    """Zaktualizuj katalog: exiftool czyta tylko nowe i zmienione pliki z input_dir."""
    config = load_config(config_path)
    if input_dir is not None:
        config = replace(config, input_dir=input_dir)
    volume = missing_volume(config.input_dir)
    if volume is not None:
        raise click.UsageError(f"Katalog wejściowy ({config.input_dir}) jest na dysku, który nie jest podłączony: {volume} nie istnieje.")
    if not config.input_dir.is_dir():
        raise click.UsageError(f"Katalog wejściowy ({config.input_dir}) nie istnieje.")

    stop_event = threading.Event()

    def handle_sigint(signum, frame):
        if stop_event.is_set():
            signal.signal(signal.SIGINT, signal.default_int_handler)
            return
        stop_event.set()
        click.echo("\nZatrzymywanie… (bieżąca paczka plików zostanie dokończona; Ctrl+C ponownie, aby przerwać natychmiast)")

    signal.signal(signal.SIGINT, handle_sigint)

    with _open(config) as catalog:
        click.echo(f"Skanowanie: {config.input_dir} -> {catalog.path}")
        result = catalog.scan(config.input_dir, log=click.echo, should_stop=stop_event.is_set)
    if result.stopped:
        click.echo("Zatrzymano na życzenie użytkownika - odczytane pliki zostały zapisane w katalogu.")
    else:
        click.echo(f"Skanowanie zakończone - {result.describe()}")


@main.command()
@_config_option
@click.option("--from", "taken_from", type=click.DateTime(["%Y-%m-%d"]), default=None, help="Zrobione od dnia (RRRR-MM-DD).")
@click.option("--to", "taken_to", type=click.DateTime(["%Y-%m-%d"]), default=None, help="Zrobione do dnia włącznie (RRRR-MM-DD).")
@click.option("--model", default=None, help="Model telefonu/aparatu z EXIF, np. \"iPhone 15 Pro\".")
@click.option("--country", default=None, help="Kraj (z reguły location albo tagu Country:).")
@click.option("--person", default=None, help="Osoba (tag Person:).")
@click.option("--no-exif-date", is_flag=True, help="Tylko pliki bez daty w EXIF (data z modyfikacji pliku).")
@click.option("--no-gps", is_flag=True, help="Tylko pliki bez GPS.")
@click.option("--limit", type=click.IntRange(min=1), default=100, show_default=True, help="Maksymalna liczba wyników.")
def search(
    config_path: str,
    taken_from: datetime | None,
    taken_to: datetime | None,
    model: str | None,
    country: str | None,
    person: str | None,
    no_exif_date: bool,
    no_gps: bool,
    limit: int,
) -> None:
    """Wyszukaj pliki w katalogu (bez skanowania - pokazuje stan z ostatniego skanu)."""
    query = CatalogQuery(
        taken_from=taken_from.date() if taken_from else None,
        taken_to=taken_to.date() if taken_to else None,
        model=model,
        country=country,
        person=person,
        without_exif_date=no_exif_date,
        without_gps=no_gps,
        limit=limit,
    )
    with _open(load_config(config_path)) as catalog:
        entries = catalog.search(query)
        total = catalog.count(query)
    for entry in entries:
        click.echo(format_entry(entry))
    click.echo(f"Znaleziono: {total}" + (f" (pokazano {len(entries)})" if total > len(entries) else ""))


def format_entry(entry: CatalogEntry) -> str:
    taken_at = f"{entry.taken_at:%Y-%m-%d %H:%M}" if entry.taken_at else "brak daty"
    if entry.date_source == "mtime":
        taken_at += "*"  # date of the file, not from EXIF
    columns = [taken_at, entry.model or "-", entry.place or "-", ", ".join(entry.tag_values("person")) or "-", str(entry.path)]
    return "  ".join(columns)


def _open(config: Config) -> Catalog:
    catalog = open_catalog(config)
    if catalog is None:
        raise click.UsageError("Katalog jest wyłączony w konfiguracji (catalog.enabled: false).")
    return catalog


if __name__ == "__main__":
    main()

from __future__ import annotations

import signal
import threading
from dataclasses import replace
from pathlib import Path

import click

from .config import load_config
from .gui import launch_app
from .pipeline import run_pipeline
from .volumes import missing_volume


@click.command()
@click.option("--config", "config_path", default="config.yaml", show_default=True, help="Path to config YAML file.")
@click.option("--input-dir", "input_dir", type=click.Path(path_type=Path), default=None, help="Override input_dir from config (defaults to current directory if no config file).")
@click.option("--output-dir", "output_dir", type=click.Path(path_type=Path), default=None, help="Override output_dir from config.")
@click.option("--gui", is_flag=True, help="Otwórz okno graficzne do wyboru ścieżek, trybu (kopiuj/przenieś), konfiguracji i uruchomienia akcji.")
@click.option("--dry-run", is_flag=True, help="Print planned actions without copying/moving files.")
def main(config_path: str, input_dir: Path | None, output_dir: Path | None, gui: bool, dry_run: bool) -> None:
    config = load_config(config_path)
    if input_dir is not None:
        config = replace(config, input_dir=input_dir)
    if output_dir is not None:
        config = replace(config, output_dir=output_dir)

    if gui:
        launch_app(config, config_path)
        return

    if config.output_dir is None:
        raise click.UsageError("output_dir must be set via --output-dir, --gui, or in the config file.")

    paths_to_check = [(config.input_dir, "wejściowy")]
    if not dry_run:
        paths_to_check.append((config.output_dir, "wyjściowy"))

    for path, label in paths_to_check:
        volume = missing_volume(path)
        if volume is not None:
            raise click.UsageError(f"Katalog {label} ({path}) jest na dysku, który nie jest podłączony: {volume} nie istnieje.")

    stop_event = threading.Event()

    def handle_sigint(signum, frame):
        if stop_event.is_set():
            # second Ctrl+C: give up waiting and let the default handler abort immediately
            signal.signal(signal.SIGINT, signal.default_int_handler)
            return
        stop_event.set()
        click.echo("\nZatrzymywanie… (bieżący plik zostanie dokończony; Ctrl+C ponownie, aby przerwać natychmiast)")

    signal.signal(signal.SIGINT, handle_sigint)

    run_pipeline(config, dry_run, log=click.echo, stop_event=stop_event)
    if stop_event.is_set():
        click.echo("Zatrzymano na życzenie użytkownika.")


if __name__ == "__main__":
    main()

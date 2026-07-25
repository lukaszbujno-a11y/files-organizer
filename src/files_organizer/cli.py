from __future__ import annotations

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

    for path, label in ((config.input_dir, "wejściowy"), (config.output_dir, "wyjściowy")):
        volume = missing_volume(path)
        if volume is not None:
            raise click.UsageError(f"Katalog {label} ({path}) jest na dysku, który nie jest podłączony: {volume} nie istnieje.")

    run_pipeline(config, dry_run, log=click.echo)


if __name__ == "__main__":
    main()

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import click

from .calendar_sources import get_calendar_source
from .config import load_config
from .exif_reader import iter_media_files, read_photo_metadata
from .gui import pick_folder
from .matcher import MatchStatus, match_photo_to_event
from .organizer import place_photo


def _missing_volume(path: Path) -> Path | None:
    """If path lives on an unmounted macOS external volume (/Volumes/<name>), return that volume's path."""
    parts = path.parts
    if len(parts) >= 3 and parts[0] == "/" and parts[1] == "Volumes":
        volume = Path(parts[0], parts[1], parts[2])
        if not volume.exists():
            return volume
    return None


@click.command()
@click.option("--config", "config_path", default="config.yaml", show_default=True, help="Path to config YAML file.")
@click.option("--input-dir", "input_dir", type=click.Path(path_type=Path), default=None, help="Override input_dir from config (defaults to current directory if no config file).")
@click.option("--output-dir", "output_dir", type=click.Path(path_type=Path), default=None, help="Override output_dir from config.")
@click.option("--gui", is_flag=True, help="Pick input/output directories via native folder pickers for this run (overrides --input-dir/--output-dir/config).")
@click.option("--dry-run", is_flag=True, help="Print planned actions without copying/moving files.")
def main(config_path: str, input_dir: Path | None, output_dir: Path | None, gui: bool, dry_run: bool) -> None:
    config = load_config(config_path)
    if input_dir is not None:
        config = replace(config, input_dir=input_dir)
    if output_dir is not None:
        config = replace(config, output_dir=output_dir)

    if gui:
        picked_input = pick_folder("Wybierz katalog źródłowy (zdjęcia do posortowania)")
        if picked_input is None:
            raise click.UsageError("Nie wybrano katalogu źródłowego.")
        picked_output = pick_folder("Wybierz katalog docelowy (gdzie zapisać posortowane pliki)")
        if picked_output is None:
            raise click.UsageError("Nie wybrano katalogu docelowego.")
        config = replace(config, input_dir=picked_input, output_dir=picked_output)

    if config.output_dir is None:
        raise click.UsageError("output_dir must be set via --output-dir, --gui, or in the config file.")

    for path, label in ((config.input_dir, "wejściowy"), (config.output_dir, "wyjściowy")):
        missing_volume = _missing_volume(path)
        if missing_volume is not None:
            raise click.UsageError(f"Katalog {label} ({path}) jest na dysku, który nie jest podłączony: {missing_volume} nie istnieje.")

    events = []
    if config.calendar:
        calendar_source = get_calendar_source(config.calendar)
        events = calendar_source.get_events()

    for path in iter_media_files(config.input_dir):
        photo = read_photo_metadata(path)
        match = match_photo_to_event(photo, events, margin_hours=config.margin_hours)

        taken_at = f"{photo.taken_at:%Y-%m-%d %H:%M:%S}" if photo.taken_at else "unknown date"

        if match.status == MatchStatus.UNMATCHED:
            click.echo(f"{photo.path} ({taken_at}) -> skipped (no matching calendar event)")
        elif dry_run:
            from .organizer import build_target_dir

            click.echo(f"{photo.path} ({taken_at}) -> {build_target_dir(config, photo, match)}")
        else:
            destination = place_photo(config, photo, match)
            click.echo(f"{photo.path} ({taken_at}) -> {destination}")


if __name__ == "__main__":
    main()

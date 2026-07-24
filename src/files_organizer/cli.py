from __future__ import annotations

import click

from .calendar_sources import get_calendar_source
from .config import load_config
from .exif_reader import iter_media_files, read_photo_metadata
from .matcher import match_photo_to_event
from .organizer import place_photo


@click.command()
@click.option("--config", "config_path", default="config.yaml", show_default=True, help="Path to config YAML file.")
@click.option("--dry-run", is_flag=True, help="Print planned actions without copying/moving files.")
def main(config_path: str, dry_run: bool) -> None:
    config = load_config(config_path)
    calendar_source = get_calendar_source(config.calendar)
    events = calendar_source.get_events()

    for path in iter_media_files(config.input_dir):
        photo = read_photo_metadata(path)
        match = match_photo_to_event(photo, events, margin_hours=config.margin_hours)

        if dry_run:
            from .organizer import build_target_dir

            click.echo(f"{photo.path} -> {build_target_dir(config, photo, match)}")
        else:
            destination = place_photo(config, photo, match)
            click.echo(f"{photo.path} -> {destination}")


if __name__ == "__main__":
    main()

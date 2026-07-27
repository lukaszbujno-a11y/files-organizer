from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .models import RecognizedLocation

PERSON_TAG_PREFIX = "Person:"
LOCATION_TAG_PREFIX = "Location:"
COUNTRY_TAG_PREFIX = "Country:"


def read_tags(path: Path) -> list[str]:
    """Read all IPTC/XMP keywords from `path` (empty list if none, or exiftool fails)."""
    try:
        result = subprocess.run(
            ["exiftool", "-j", "-Keywords", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)[0]
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError, IndexError):
        return []

    keywords = data.get("Keywords")
    if keywords is None:
        return []
    if isinstance(keywords, str):
        return [keywords]
    return list(keywords)


def _read_tagged_values(path: Path, prefix: str) -> list[str]:
    return [tag[len(prefix) :] for tag in read_tags(path) if tag.startswith(prefix)]


def _write_tagged_values_multi(path: Path, prefix_values: list[tuple[str, list[str]]]) -> None:
    """Add a `<prefix><value>` keyword for each (prefix, values) pair not already tagged on `path`.

    Writes to the Keywords tag (IPTC + XMP-dc:Subject) in a single exiftool call, so when
    multiple prefixes are given (e.g. Location: + Country:) a reader never observes one
    written without the other. Namespacing by prefix keeps these keywords from colliding with
    others already on the file. Idempotent: re-tagging the same value is a no-op.
    """
    new_tags = []
    for prefix, values in prefix_values:
        already_tagged = set(_read_tagged_values(path, prefix))
        new_tags += [f"{prefix}{value}" for value in values if value not in already_tagged]
    if not new_tags:
        return

    args = ["exiftool", "-overwrite_original"]
    args += [f"-Keywords+={tag}" for tag in new_tags]
    args.append(str(path))
    subprocess.run(args, capture_output=True, text=True, check=True)


def _write_tagged_values(path: Path, prefix: str, values: list[str]) -> None:
    _write_tagged_values_multi(path, [(prefix, values)])


def _remove_tagged_values_multi(path: Path, prefixes: list[str]) -> list[str]:
    """Remove every keyword under any of `prefixes` from `path`, leaving other keywords untouched.

    Removes all prefixes in a single exiftool call, for the same all-or-nothing reason
    `_write_tagged_values_multi` writes them together. Returns the removed values, grouped by
    prefix in the order given (empty list if the file had none of them).
    """
    tagged_by_prefix = [(prefix, _read_tagged_values(path, prefix)) for prefix in prefixes]
    tagged = [value for _, values in tagged_by_prefix for value in values]
    if not tagged:
        return []

    args = ["exiftool", "-overwrite_original"]
    for prefix, values in tagged_by_prefix:
        args += [f"-Keywords-={prefix}{value}" for value in values]
    args.append(str(path))
    subprocess.run(args, capture_output=True, text=True, check=True)
    return tagged


def _remove_tagged_values(path: Path, prefix: str) -> list[str]:
    return _remove_tagged_values_multi(path, [prefix])


def read_tagged_people(path: Path) -> list[str]:
    """Names already tagged on `path` via a `Person:<name>` keyword."""
    return _read_tagged_values(path, PERSON_TAG_PREFIX)


def write_tags(path: Path, people: list[str]) -> None:
    """Add a `Person:<name>` keyword for each name not already tagged on `path`."""
    _write_tagged_values(path, PERSON_TAG_PREFIX, people)


def remove_person_tags(path: Path) -> list[str]:
    """Remove every `Person:<name>` keyword from `path`, leaving other keywords untouched."""
    return _remove_tagged_values(path, PERSON_TAG_PREFIX)


def read_tagged_locations(path: Path) -> list[str]:
    """City names already tagged on `path` via a `Location:<city>` keyword."""
    return _read_tagged_values(path, LOCATION_TAG_PREFIX)


def read_tagged_countries(path: Path) -> list[str]:
    """Country names already tagged on `path` via a `Country:<country>` keyword."""
    return _read_tagged_values(path, COUNTRY_TAG_PREFIX)


def write_location_tags(path: Path, location: RecognizedLocation) -> None:
    """Add `Location:<city>` and `Country:<country>` keywords for `location`, unless already tagged."""
    _write_tagged_values_multi(
        path, [(LOCATION_TAG_PREFIX, [location.city]), (COUNTRY_TAG_PREFIX, [location.country])]
    )


def remove_location_tags(path: Path) -> list[str]:
    """Remove every `Location:` and `Country:` keyword from `path`, leaving other keywords untouched.

    Returns the removed values (cities followed by countries), empty if the file had none.
    """
    return _remove_tagged_values_multi(path, [LOCATION_TAG_PREFIX, COUNTRY_TAG_PREFIX])

from __future__ import annotations

import json
import subprocess
from pathlib import Path

PERSON_TAG_PREFIX = "Person:"


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


def read_tagged_people(path: Path) -> list[str]:
    """Names already tagged on `path` via a `Person:<name>` keyword."""
    return [tag[len(PERSON_TAG_PREFIX) :] for tag in read_tags(path) if tag.startswith(PERSON_TAG_PREFIX)]


def write_tags(path: Path, people: list[str]) -> None:
    """Add a `Person:<name>` keyword for each name not already tagged on `path`.

    Writes to the Keywords tag (IPTC + XMP-dc:Subject), namespaced with `Person:` so it
    doesn't collide with other keywords already on the file. Idempotent: re-tagging the
    same person is a no-op.
    """
    already_tagged = set(read_tagged_people(path))
    new_tags = [f"{PERSON_TAG_PREFIX}{name}" for name in people if name not in already_tagged]
    if not new_tags:
        return

    args = ["exiftool", "-overwrite_original"]
    args += [f"-Keywords+={tag}" for tag in new_tags]
    args.append(str(path))
    subprocess.run(args, capture_output=True, text=True, check=True)

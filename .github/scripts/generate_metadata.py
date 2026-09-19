#!/usr/bin/env python3

from __future__ import annotations

import colorsys
import datetime
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from PIL import Image


# ============================================================
# CONFIG
# ============================================================

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
}

THUMB_SIZE = (640, 360)
PREVIEW_SIZE = (1920, 1080)

REPO_ROOT = Path(__file__).resolve().parents[2]

THUMB_DIR = REPO_ROOT / "thumbnails"
PREVIEW_DIR = REPO_ROOT / "previews"

METADATA_FILE = REPO_ROOT / "wallpapers.json"
DATES_FILE = REPO_ROOT / ".github" / "data" / "wallpaper-dates.json"

# Increase this whenever the metadata/preview generation logic changes.
METADATA_VERSION = 6

# Generated / infrastructure directories that are NOT wallpaper sources.
IGNORED_DIRS = {
    ".git",
    ".github",
    "thumbnails",
    "previews",
}


# ============================================================
# PATH HELPERS
# ============================================================

def relative_path(path: Path) -> str:
    """
    Convert an absolute/local path into a stable repository-relative
    POSIX path.

    Example:
        /repo/Cars/BMW/m4.jpg
    becomes:
        Cars/BMW/m4.jpg
    """
    return path.relative_to(REPO_ROOT).as_posix()


def is_wallpaper(path: Path) -> bool:
    """
    Return True only for real wallpaper image files.

    Any image inside ignored/generated directories is skipped.
    """
    if not path.is_file():
        return False

    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return False

    rel = path.relative_to(REPO_ROOT)

    # Ignore generated/infrastructure directories.
    for parent in rel.parts[:-1]:
        if parent in IGNORED_DIRS:
            return False

    return True


def find_wallpapers() -> list[Path]:
    """
    Recursively discover wallpapers anywhere inside the repository.

    This means you can add:

        Abstract/
        Anime/
        Cars/
        Dark/
        Minimal/
        Cars/BMW/
        Cars/Porsche/
        Anime/JJK/

    without modifying this script.
    """
    files = [
        path
        for path in REPO_ROOT.rglob("*")
        if is_wallpaper(path)
    ]

    return sorted(
        files,
        key=lambda p: relative_path(p).lower(),
    )


# ============================================================
# SAFE GENERATED FILENAMES
# ============================================================

def derivative_name(kind: str, wallpaper_path: str) -> str:
    """
    Generate a collision-safe filename for generated thumbnails/previews.

    This is important because:

        Anime/fav.jpg
        Cars/fav.jpg

    must NOT generate the same thumbnail filename.

    The full relative path is hashed.
    """
    digest = hashlib.sha1(
        wallpaper_path.encode("utf-8")
    ).hexdigest()[:16]

    return f"{kind}_{digest}.webp"


# ============================================================
# WALLHAVEN ID
# ============================================================

def get_wallhaven_id(filename: str):
    match = re.search(
        r"wallhaven-([a-z0-9]+)",
        filename,
        re.IGNORECASE,
    )

    if match:
        return match.group(1)

    return None


# ============================================================
# DATE HANDLING
# ============================================================

def get_git_mtime(rel_path: str) -> str:
    """
    Try to retrieve the last git commit date for the specific file.

    The GitHub Action uses a shallow checkout, so this may not always
    be available. In that case filesystem mtime is used as fallback.
    """
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "-1",
                "--format=%cI",
                "--",
                rel_path,
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )

        timestamp = result.stdout.strip()

        if timestamp:
            return timestamp

    except Exception:
        pass

    path = REPO_ROOT / rel_path

    return datetime.datetime.fromtimestamp(
        path.stat().st_mtime,
        datetime.timezone.utc,
    ).astimezone().isoformat()


def load_wallpaper_dates() -> dict[str, str]:
    """
    Load the persistent filename/path -> date map.

    The key is the FULL relative path, not just the filename.
    """
    if not DATES_FILE.exists():
        return {}

    try:
        data = json.loads(
            DATES_FILE.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(data, dict):
            return data

    except Exception as exc:
        print(
            f"Warning: could not load {DATES_FILE}: {exc}"
        )

    return {}


# ============================================================
# COLOR ANALYSIS
# ============================================================

def get_dominant_color(img: Image.Image) -> str:
    """
    Approximate dominant/average color.
    """
    try:
        working = img.convert("RGB")

        working = working.resize(
            (1, 1),
            resample=Image.Resampling.BILINEAR,
        )

        r, g, b = working.getpixel((0, 0))

        return "#{:02x}{:02x}{:02x}".format(
            r,
            g,
            b,
        )

    except Exception:
        return "#47464f"


def get_color_groups(img: Image.Image) -> list[str]:
    """
    Classify meaningful color groups in the wallpaper.

    Matches the general grouping used by the original repository.
    """
    working = img.convert("RGB")

    grid_size = 8

    working = working.resize(
        (grid_size, grid_size),
        resample=Image.Resampling.BILINEAR,
    )

    color_counts: dict[str, int] = {}

    for x in range(grid_size):
        for y in range(grid_size):

            r, g, b = working.getpixel(
                (x, y)
            )

            r_norm = r / 255.0
            g_norm = g / 255.0
            b_norm = b / 255.0

            h, s, v = colorsys.rgb_to_hsv(
                r_norm,
                g_norm,
                b_norm,
            )

            h_deg = h * 360.0

            # Ignore near-gray and extremely dark pixels.
            if s < 0.25 or v < 0.20:
                continue

            group = None

            if h_deg < 10 or h_deg >= 345:
                group = "Red"

            elif h_deg < 45:
                group = "Orange"

            elif h_deg < 70:
                group = "Yellow"

            elif h_deg < 160:
                group = "Green"

            elif h_deg < 250:
                group = "Blue"

            elif h_deg < 345:
                group = "Purple"

            if group:
                color_counts[group] = (
                    color_counts.get(group, 0) + 1
                )

    # 12/64 ≈ 19% of the sampled image.
    significant_groups = [
        group
        for group, count in color_counts.items()
        if count >= 12
    ]

    # Fallback for wallpapers where no color reaches the threshold.
    if not significant_groups and color_counts:

        top_color = max(
            color_counts,
            key=color_counts.get,
        )

        if color_counts[top_color] >= 6:
            significant_groups = [top_color]

    return sorted(significant_groups)


# ============================================================
# IMAGE PROCESSING
# ============================================================

def generate_preview(
    source: Path,
    destination: Path,
) -> None:
    """
    Generate the 1920x1080 max preview.

    IMPORTANT:
    source is NEVER modified.
    """
    if destination.exists():
        return

    with Image.open(source) as img:

        preview = img.copy()

        preview.thumbnail(
            PREVIEW_SIZE
        )

        preview.save(
            destination,
            "WEBP",
            optimize=True,
            quality=85,
        )


def generate_thumbnail(
    source: Path,
    destination: Path,
) -> None:
    """
    Generate the 640x360 thumbnail.

    IMPORTANT:
    source is NEVER modified.
    """
    if destination.exists():
        return

    with Image.open(source) as img:

        thumbnail = img.copy()

        thumbnail.thumbnail(
            THUMB_SIZE
        )

        thumbnail.save(
            destination,
            "WEBP",
            optimize=True,
            quality=85,
        )


def generate_with_imagemagick(
    source: Path,
    preview: Path,
    thumbnail: Path,
) -> None:
    """
    Fallback if Pillow cannot decode the wallpaper.
    """

    if not preview.exists():

        try:

            subprocess.run(
                [
                    "magick",
                    str(source),
                    "-thumbnail",
                    "1920x1080>",
                    str(preview),
                ],
                check=True,
            )

        except (FileNotFoundError, subprocess.CalledProcessError):

            subprocess.run(
                [
                    "convert",
                    str(source),
                    "-thumbnail",
                    "1920x1080>",
                    str(preview),
                ],
                check=True,
            )

    if not thumbnail.exists():

        try:

            subprocess.run(
                [
                    "magick",
                    str(source),
                    "-thumbnail",
                    "640x360>",
                    str(thumbnail),
                ],
                check=True,
            )

        except (FileNotFoundError, subprocess.CalledProcessError):

            subprocess.run(
                [
                    "convert",
                    str(source),
                    "-thumbnail",
                    "640x360>",
                    str(thumbnail),
                ],
                check=True,
            )


# ============================================================
# MAIN METADATA GENERATION
# ============================================================

def generate_metadata() -> None:

    THUMB_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    PREVIEW_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Load existing metadata
    # --------------------------------------------------------

    old_metadata: dict[str, dict] = {}

    if METADATA_FILE.exists():

        try:

            data = json.loads(
                METADATA_FILE.read_text(
                    encoding="utf-8"
                )
            )

            if isinstance(data, list):

                for item in data:

                    key = (
                        item.get("path")
                        or item.get("filename")
                    )

                    if key:
                        old_metadata[key] = item

        except Exception as exc:

            print(
                f"Warning: could not load "
                f"{METADATA_FILE}: {exc}"
            )

    # --------------------------------------------------------
    # Discover ALL wallpapers recursively
    # --------------------------------------------------------

    current_files = find_wallpapers()

    if not current_files:

        raise RuntimeError(
            "No wallpaper images were found."
        )

    print(
        f"Found {len(current_files)} wallpaper(s)."
    )

    # --------------------------------------------------------
    # Load persistent dates
    # --------------------------------------------------------

    wallpaper_dates = (
        load_wallpaper_dates()
    )

    wallpapers = []

    processed_count = 0
    skipped_count = 0

    current_thumbnail_names = set()
    current_preview_names = set()

    # --------------------------------------------------------
    # Process each wallpaper independently
    # --------------------------------------------------------

    for source in current_files:

        rel_path = relative_path(source)

        filename = source.name

        thumb_name = derivative_name(
            "thumb",
            rel_path,
        )

        preview_name = derivative_name(
            "preview",
            rel_path,
        )

        thumb_path = (
            THUMB_DIR /
            thumb_name
        )

        preview_path = (
            PREVIEW_DIR /
            preview_name
        )

        current_thumbnail_names.add(
            thumb_name
        )

        current_preview_names.add(
            preview_name
        )

        old = old_metadata.get(
            rel_path
        )

        # ----------------------------------------------------
        # Reuse previous generated metadata
        # ----------------------------------------------------

        if (
            old
            and thumb_path.exists()
            and preview_path.exists()
            and old.get("version")
                == METADATA_VERSION
            and old.get("resolution")
                != "Unknown"
        ):

            wallpapers.append(
                old
            )

            skipped_count += 1

            continue

        print(
            f"Processing: {rel_path}"
        )

        processed_count += 1

        # ----------------------------------------------------
        # Date
        # ----------------------------------------------------

        mtime = (
            wallpaper_dates.get(rel_path)
            or get_git_mtime(rel_path)
        )

        resolution = "Unknown"

        dominant_color = "#47464f"

        color_groups = []

        # ----------------------------------------------------
        # Read source image
        # ----------------------------------------------------

        try:

            with Image.open(source) as img:

                width, height = img.size

                resolution = (
                    f"{width}x{height}"
                )

                dominant_color = (
                    get_dominant_color(img)
                )

                color_groups = (
                    get_color_groups(img)
                )

                # ------------------------------
                # Generate preview
                # ------------------------------

                generate_preview(
                    source,
                    preview_path,
                )

                # ------------------------------
                # Generate thumbnail
                # ------------------------------

                generate_thumbnail(
                    source,
                    thumb_path,
                )

        except Exception as exc:

            print(
                f"Pillow error for "
                f"{rel_path}: {exc}"
            )

            # ------------------------------------
            # ImageMagick resolution fallback
            # ------------------------------------

            try:

                result = subprocess.run(
                    [
                        "identify",
                        "-format",
                        "%wx%h",
                        str(source),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=True,
                )

                value = result.stdout.strip()

                if value:
                    resolution = value

            except Exception as res_exc:

                print(
                    f"Resolution fallback failed: "
                    f"{res_exc}"
                )

            # ------------------------------------
            # ImageMagick preview/thumbnail
            # ------------------------------------

            try:

                generate_with_imagemagick(
                    source,
                    preview_path,
                    thumb_path,
                )

            except Exception as image_exc:

                print(
                    f"ImageMagick fallback failed "
                    f"for {rel_path}: "
                    f"{image_exc}"
                )

        # ----------------------------------------------------
        # Record metadata
        # ----------------------------------------------------

        wallpaper = {
            # Filename retained for compatibility
            # with the existing website.
            "filename": filename,

            # FULL path uniquely identifies the wallpaper.
            "path": rel_path,

            "thumbnail": (
                thumb_path
                .relative_to(REPO_ROOT)
                .as_posix()
            ),

            "preview": (
                preview_path
                .relative_to(REPO_ROOT)
                .as_posix()
            ),

            "mtime": mtime,

            "resolution": resolution,

            "color": dominant_color,

            "color_groups": color_groups,

            "wallhaven_id":
                get_wallhaven_id(filename),

            "version":
                METADATA_VERSION,
        }

        wallpapers.append(
            wallpaper
        )

        # ----------------------------------------------------
        # Persist date using FULL path
        # ----------------------------------------------------

        if rel_path not in wallpaper_dates:

            wallpaper_dates[
                rel_path
            ] = mtime

    # --------------------------------------------------------
    # Newest first
    # --------------------------------------------------------

    wallpapers.sort(
        key=lambda item: item["mtime"],
        reverse=True,
    )

    # --------------------------------------------------------
    # Write wallpapers.json
    # --------------------------------------------------------

    METADATA_FILE.write_text(
        json.dumps(
            wallpapers,
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Write persistent dates
    # --------------------------------------------------------

    DATES_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    DATES_FILE.write_text(
        json.dumps(
            wallpaper_dates,
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Delete stale thumbnails
    # --------------------------------------------------------

    if THUMB_DIR.exists():

        for file in THUMB_DIR.iterdir():

            if not file.is_file():
                continue

            if file.name == "thumb_social_preview.webp":
                continue

            if file.name not in current_thumbnail_names:

                try:
                    file.unlink()
                except OSError:
                    pass

    # --------------------------------------------------------
    # Delete stale previews
    # --------------------------------------------------------

    if PREVIEW_DIR.exists():

        for file in PREVIEW_DIR.iterdir():

            if not file.is_file():
                continue

            if file.name not in current_preview_names:

                try:
                    file.unlink()
                except OSError:
                    pass

    # --------------------------------------------------------
    # Generate social preview from newest wallpaper
    # --------------------------------------------------------

    if wallpapers:

        newest = wallpapers[0]

        source = (
            REPO_ROOT /
            newest["path"]
        )

        social_preview = (
            THUMB_DIR /
            "thumb_social_preview.webp"
        )

        try:

            with Image.open(
                source
            ) as img:

                thumbnail = img.copy()

                thumbnail.thumbnail(
                    THUMB_SIZE
                )

                thumbnail.save(
                    social_preview,
                    "WEBP",
                    optimize=True,
                    quality=85,
                )

        except Exception as exc:

            print(
                f"Social preview generation failed: "
                f"{exc}"
            )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print()
    print(
        "=========================================="
    )
    print(
        " Wallpaper metadata generation complete"
    )
    print(
        "=========================================="
    )
    print(
        f"Total wallpapers : {len(wallpapers)}"
    )
    print(
        f"Processed        : {processed_count}"
    )
    print(
        f"Reused           : {skipped_count}"
    )
    print(
        "Original files   : untouched"
    )
    print(
        "=========================================="
    )


if __name__ == "__main__":
    generate_metadata()

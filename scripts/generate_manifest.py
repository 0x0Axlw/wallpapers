#!/usr/bin/env python3

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

DATES_FILE = ROOT / ".github" / "data" / "wallpaper-dates.json"
OUTPUT_FILE = ROOT / "manifest.json"


def main():
    if not DATES_FILE.exists():
        print(f"Missing: {DATES_FILE}", file=sys.stderr)
        return 1

    try:
        dates = json.loads(
            DATES_FILE.read_text(encoding="utf-8")
        )
    except Exception as exc:
        print(f"Could not read dates: {exc}", file=sys.stderr)
        return 1

    if not isinstance(dates, dict) or not dates:
        print("No wallpaper dates found.", file=sys.stderr)
        return 1

    wallpapers = []

    for path, date in dates.items():
        wallpapers.append({
            "filename": Path(path).name,
            "path": path,
            "date": date,
        })

    wallpapers.sort(
        key=lambda item: item["date"],
        reverse=True,
    )

    manifest = {
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "wallpapers": wallpapers,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    print(
        f"✅ Wrote {len(wallpapers)} wallpapers to {OUTPUT_FILE}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())

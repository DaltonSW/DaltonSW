#!/usr/bin/env python3
"""Recolor assets/*.json so each banner's gradient flows into the next,
in whatever order the banners actually appear in README.md.

Reorder the README, rerun this script, done -- no hand-edited hex codes.

Usage:
  scripts/sync_banner_colors.py              # update JSON + re-render PNGs
  scripts/sync_banner_colors.py --dry-run     # show the plan, touch nothing
  scripts/sync_banner_colors.py --no-render   # update JSON, skip PNG render
  scripts/sync_banner_colors.py --start-hue 40
"""

import argparse
import colorsys
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
ASSETS = REPO_ROOT / "assets"

SATURATION = 0.72
LIGHTNESS = 0.60

BANNER_RE = re.compile(r'assets/([^"/]+?)_thin_banner\.png')


def banner_order() -> list[str]:
    """Names in first-appearance (i.e. document/scroll) order, deduped."""
    seen: dict[str, None] = {}
    for m in BANNER_RE.finditer(README.read_text()):
        seen.setdefault(m.group(1), None)
    return list(seen)


def hex_at(hue: float) -> str:
    r, g, b = colorsys.hls_to_rgb((hue % 360) / 360, LIGHTNESS, SATURATION)
    return "#{:02X}{:02X}{:02X}".format(round(r * 255), round(g * 255), round(b * 255))


def build_palette(names: list[str], start_hue: float) -> dict[str, tuple[str, str]]:
    # N banners need N+1 anchors; the last anchor is start_hue + 360, so the
    # final banner's gradient hands off almost exactly to the first banner's
    # starting color, closing the loop.
    n = len(names)
    anchors = [start_hue + 360 * i / n for i in range(n + 1)]
    return {
        name: (hex_at(anchors[i]), hex_at(anchors[i + 1]))
        for i, name in enumerate(names)
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    ap.add_argument("--no-render", action="store_true", help="update JSON only, skip `headline render`")
    ap.add_argument("--start-hue", type=float, default=200.0, help="hue (0-360) the first banner starts at (default 200)")
    args = ap.parse_args()

    names = banner_order()
    if not names:
        print(f"no assets/*_thin_banner.png references found in {README}", file=sys.stderr)
        return 1

    missing = [n for n in names if not (ASSETS / f"{n}.json").exists()]
    if missing:
        print("README references banners with no assets/<name>.json config:", file=sys.stderr)
        for n in missing:
            print(f"  - {n}", file=sys.stderr)
        return 1

    palette = build_palette(names, args.start_hue)

    width = max(len(n) for n in names)
    for i, name in enumerate(names):
        c0, c1 = palette[name]
        print(f"{i+1:2d}. {name:<{width}}  {c0} -> {c1}")

    if args.dry_run:
        print("\n(dry run -- nothing written)")
        return 0

    for name, (c0, c1) in palette.items():
        cfg_path = ASSETS / f"{name}.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["title"]["colors"] = [c0, c1]
        cfg["title"]["gradient_dir"] = "right"
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")

    print(f"\nupdated {len(names)} configs")

    if not args.no_render:
        print("rendering...")
        for name in names:
            subprocess.run(
                [
                    "headline", "render", "thin_banner",
                    "--config", f"{name}.json",
                    "-o", f"{name}_thin_banner.png",
                ],
                cwd=ASSETS,
                check=True,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Recolor assets/*.json so each banner's gradient flows into the next,
in whatever order the banners actually appear in README.md.

Reorder the README, rerun this script, done -- no hand-edited hex codes.

Colors are picked in OKLCH at a FIXED lightness, not in HLS/HSV. That
distinction is the whole point of this script, so: HSL's "L" and HSV's "V"
are not perceptual lightness. An evenly-spaced hue ramp at constant HSL
S/L looks mathematically uniform and reads wildly uneven -- the previous
S=0.72/L=0.60 palette spanned OKLCH lightness 0.527 to 0.863 (a 64%
spread), which pushed title-vs-panel contrast from 2.90:1 (#5550E2, below
WCAG AA) up to 9.62:1 (#C3E250). Stacked in README order -- which follows
the hue chain -- that made the page ramp from dim, receding blues at the
top to blazing yellow-greens at the bottom. Constant OKLCH L holds every
banner at the same visual weight; contrast now sits in a 6.1-6.9 band.

The cost is chroma: a constant-L ramp can only be as saturated as its most
gamut-limited hue (cyan ~191 deg at this L), so CHROMA_CAP is deliberately
modest. Raising it doesn't make the vivid hues more vivid -- it just
reintroduces the unevenness, because the cap only binds on some hues.

Usage:
  scripts/sync_banner_colors.py              # update JSON + re-render PNGs
  scripts/sync_banner_colors.py --dry-run     # show the plan, touch nothing
  scripts/sync_banner_colors.py --no-render   # update JSON, skip PNG render
  scripts/sync_banner_colors.py --start-hue 40
"""

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
ASSETS = REPO_ROOT / "assets"

# OKLCH lightness every gradient stop is pinned to. 0.74 is the sweet spot:
# it's where the worst-case achievable chroma across a full hue circle peaks
# (below it cyan limits you, above it blue does), and it keeps titles ~6.5:1
# against their own tinted panel.
LIGHTNESS = 0.74
# Upper bound on chroma; hues that can't reach it in sRGB get clamped down to
# their own gamut edge. See the module docstring before raising this.
CHROMA_CAP = 0.17

# Pinned so it stops being random. headline seeds background.tint_amount from
# the project name when the config omits it (seededFloatInRange 0.12-0.22),
# which had these banners' panels ranging 0.121 to 0.217 -- i.e. panel
# darkness varied per project for no reason anyone chose.
TINT_AMOUNT = 0.16

# Custom layout: fixed-width subtitle column, so every banner shares one
# vertical axis. Path is relative to ASSETS (headline reads it from cwd, and
# we render with cwd=ASSETS below).
THIN_BANNER_TEMPLATE = "thin_banner.html.tmpl"

# Uniform across every banner on purpose: a per-project size (or an autofit)
# would give each title a different cap height, which is the inconsistency
# these banners were rebuilt to get rid of. 45 is the ceiling -- at 46 the
# longest one-line title ("I Wanna Hookshot") wraps against the template's
# title box. See the sizing note in thin_banner.html.tmpl before changing it.
THIN_BANNER_TITLE_SIZE = 45

BANNER_RE = re.compile(r'assets/([^"/]+?)_thin_banner\.png')


def banner_order() -> list[str]:
    """Names in first-appearance (i.e. document/scroll) order, deduped."""
    seen: dict[str, None] = {}
    for m in BANNER_RE.finditer(README.read_text()):
        seen.setdefault(m.group(1), None)
    return list(seen)


def oklch_to_srgb(light: float, chroma: float, hue_deg: float):
    """OKLCH -> 8-bit sRGB, or None if the color falls outside the sRGB gamut."""
    h = math.radians(hue_deg)
    a, b = chroma * math.cos(h), chroma * math.sin(h)

    l_ = light + 0.3963377774 * a + 0.2158037573 * b
    m_ = light - 0.1055613458 * a - 0.0638541728 * b
    s_ = light - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_**3, m_**3, s_**3

    lin = (
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )

    out = []
    for v in lin:
        if v < 0.0 or v > 1.0:
            return None
        out.append(12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055)
    return tuple(round(v * 255) for v in out)


def max_chroma(light: float, hue_deg: float) -> float:
    """Largest in-gamut chroma at this lightness/hue, by bisection."""
    lo, hi = 0.0, 0.4
    for _ in range(40):
        mid = (lo + hi) / 2
        if oklch_to_srgb(light, mid, hue_deg):
            lo = mid
        else:
            hi = mid
    return lo


def hex_at(hue: float) -> str:
    hue %= 360
    # 0.95 keeps us just inside the gamut edge; landing exactly on it lets
    # 8-bit rounding push a channel back out of range.
    chroma = min(CHROMA_CAP, max_chroma(LIGHTNESS, hue) * 0.95)
    rgb = oklch_to_srgb(LIGHTNESS, chroma, hue)
    while rgb is None and chroma > 0:
        chroma -= 0.001
        rgb = oklch_to_srgb(LIGHTNESS, chroma, hue)
    return "#{:02X}{:02X}{:02X}".format(*rgb)


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
    ap.add_argument("--start-hue", type=float, default=233.0, help="hue (0-360) the first banner starts at (default 233)")
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

    if not (ASSETS / THIN_BANNER_TEMPLATE).exists():
        print(f"missing layout template: {ASSETS / THIN_BANNER_TEMPLATE}", file=sys.stderr)
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
        cfg.setdefault("background", {})["tint_amount"] = TINT_AMOUNT
        thin = cfg.setdefault("output", {}).setdefault("thin_banner", {})
        thin["template"] = THIN_BANNER_TEMPLATE
        thin["title_size"] = THIN_BANNER_TITLE_SIZE
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

#!/usr/bin/env python3
"""Compatibility entry point for the original standalone script."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from google_maps_reviews.cli import (  # noqa: E402
    export_reviews, maps_url, merge_reviews, next_stagnant_count,
    full_coverage_verified, main,
)

if __name__ == "__main__":
    raise SystemExit(main())

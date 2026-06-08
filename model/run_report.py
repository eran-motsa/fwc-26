"""16:30 Asia/Jerusalem job: refit ratings, predict, build daily snapshot."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TZ_LOCAL  # noqa: E402
from model import predict, ratings, report  # noqa: E402


def main() -> None:
    today = datetime.now(ZoneInfo(TZ_LOCAL)).date().isoformat()
    print(f"=== Model + report for {today} ===")
    ratings.run()
    predict.predict_day(today)
    report.save_day(today)
    print("Report complete.")


if __name__ == "__main__":
    main()

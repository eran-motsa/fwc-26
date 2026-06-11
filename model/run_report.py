"""16:30 Asia/Jerusalem job: refit ratings, predict, build daily snapshot."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TZ_LOCAL  # noqa: E402
from model import predict, ratings, report  # noqa: E402


def main() -> None:
    now = datetime.now(ZoneInfo(TZ_LOCAL))
    today = now.date().isoformat()
    tomorrow = (now.date() + timedelta(days=1)).isoformat()
    print(f"=== Model + report for {today} ===")
    ratings.run()
    predict.predict_day(today)
    report.save_day(today)
    predict.predict_day(tomorrow)
    report.save_day(tomorrow)
    print("Report complete.")


if __name__ == "__main__":
    main()

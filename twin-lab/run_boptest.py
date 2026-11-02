"""L2: record readings from a BOPTEST building into a CSV file.

First time, check the point names:
    python run_boptest.py --list
Then record (default: 3 days from 15 January, one reading every 15 minutes):
    python run_boptest.py

Output: data/boptest_bestest_air.csv, one row per reading, in the canonical
message shape. Needs internet access to api.boptest.net.
"""

import argparse
import csv
from pathlib import Path

from twinlab.boptest import POINTS, BoptestClient, check_points, to_rows

DAY = 86400


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list", action="store_true", help="print every sensor point BOPTEST offers, then stop")
    p.add_argument("--testcase", default="bestest_air")
    p.add_argument("--start-day", type=float, default=14, help="day of the year to start (0 = 1 Jan)")
    p.add_argument("--days", type=float, default=3, help="how many days to record")
    p.add_argument("--step", type=float, default=900, help="seconds between readings")
    p.add_argument("--warmup-days", type=float, default=7, help="days BOPTEST runs first so the building isn't starting cold")
    p.add_argument("--out", default="data/boptest_bestest_air.csv")
    p.add_argument("--url", default="https://api.boptest.net")
    args = p.parse_args()

    client = BoptestClient(args.url)
    print(f"selecting test case {args.testcase} ...")
    client.select(args.testcase)
    try:
        point_list = client.measurements()

        if args.list:
            for name, info in sorted(point_list.items()):
                mark = "  <- used" if name in POINTS else ""
                print(f"{name:40s} {str(info.get('Unit')):8s} {info.get('Description', '')}{mark}")
            return

        plan = check_points(point_list)  # stops here with a clear message if names are wrong
        client.initialize(start_time=args.start_day * DAY, warmup_period=args.warmup_days * DAY)
        client.set_step(args.step)

        steps = int(args.days * DAY / args.step)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="") as f:
            writer = None
            for i in range(steps):
                rows = to_rows(client.advance(), plan, source=f"boptest:{args.testcase}")
                if writer is None:
                    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                    writer.writeheader()
                writer.writerows(rows)
                if (i + 1) % 24 == 0 or i + 1 == steps:
                    print(f"  {i + 1}/{steps} steps  ({rows[0]['sensor_time']})")
        print(f"saved {out}")
    finally:
        client.stop()  # always free our run on the server, even after an error


if __name__ == "__main__":
    main()

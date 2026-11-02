import re
import sys

from app.estate.tasks import sync_estate

ORG = re.compile(r"^[A-Za-z0-9-]{8,64}$")
RANGE = re.compile(r"^(7d|30d|mtd|qtr)$")


def main() -> None:
    org_id, project_id, range_id = sys.argv[1:4]
    if not ORG.match(org_id) or not ORG.match(project_id) or not RANGE.match(range_id):
        raise SystemExit(2)
    sync_estate.delay(org_id, project_id, range_id)


if __name__ == "__main__":
    main()

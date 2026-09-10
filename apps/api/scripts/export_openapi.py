import json
from pathlib import Path

from hymail_api.main import app

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT = REPO_ROOT / "packages" / "api-client" / "openapi.json"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
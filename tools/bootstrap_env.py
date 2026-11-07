"""Create a local .env with freshly generated secrets. Never overwrites an existing value."""
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

GENERATED = {
    "POSTGRES_PASSWORD": lambda: secrets.token_urlsafe(24),
    "ORRFIN_OWNER_DB_PASSWORD": lambda: secrets.token_urlsafe(24),
    "ORRFIN_APP_DB_PASSWORD": lambda: secrets.token_urlsafe(24),
    "ORRFIN_SECRET_KEY": lambda: secrets.token_urlsafe(48),
    "S3_ACCESS_KEY": lambda: "orrfin" + secrets.token_hex(6),
    "S3_SECRET_KEY": lambda: secrets.token_urlsafe(32),
}
OPTIONAL = [
    "ANTHROPIC_API_KEY",
    "GROQ_API_KEY",
    "TINYFISH_API_KEY",
    "HINDSIGHT_API_KEY",
]


def main() -> None:
    existing: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                existing[key.strip()] = value

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    added = []
    for key, make in GENERATED.items():
        if not existing.get(key):
            lines = [line for line in lines if not line.startswith(key + "=")]
            lines.append(f"{key}={make()}")
            added.append(key)
    for key in OPTIONAL:
        if key not in existing:
            lines.append(f"{key}=")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{ENV_PATH.name}: generated {len(added)} secret(s). Values are not printed.")


if __name__ == "__main__":
    main()

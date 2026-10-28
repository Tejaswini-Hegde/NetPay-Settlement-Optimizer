"""Settings come from environment variables / a local .env file. Never hardcode keys."""
from __future__ import annotations
import os
from dataclasses import dataclass

SANDBOX_URL = "https://api-m.sandbox.paypal.com"


def _read_dotenv(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


@dataclass(frozen=True)
class Settings:
    client_id: str
    client_secret: str
    base_url: str = SANDBOX_URL

    @classmethod
    def from_env(cls, env_file: str = ".env", environ: dict | None = None) -> "Settings":
        env = {**_read_dotenv(env_file), **(environ if environ is not None else os.environ)}
        cid, sec = env.get("PAYPAL_CLIENT_ID", "").strip(), env.get("PAYPAL_CLIENT_SECRET", "").strip()
        if not cid or not sec:
            raise RuntimeError("Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env or your environment")
        if any(c.isspace() for c in cid + sec):
            raise RuntimeError("Credentials contain whitespace - re-copy them from the dashboard")
        base = env.get("PAYPAL_BASE_URL", SANDBOX_URL).rstrip("/")
        if base != SANDBOX_URL:
            raise RuntimeError(f"Refusing non-sandbox base URL: {base}")
        return cls(cid, sec, base)

#!/usr/bin/env python3
"""Launch Blinks Bright.

Single entry point — the app creates its SQLite schema and seeds demo data on
startup, then serves on port 8051.

    python run.py
"""
import uvicorn

from app.config import settings


def main() -> None:
    print(f"\n  {settings.app_name}  ->  {settings.base_url.rstrip('/')}\n")
    # proxy_headers/forwarded-allow-ips so request.base_url reflects the real
    # public host+scheme when running behind a tunnel / reverse proxy.
    uvicorn.run("app.main:app", host=settings.host, port=settings.port,
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()

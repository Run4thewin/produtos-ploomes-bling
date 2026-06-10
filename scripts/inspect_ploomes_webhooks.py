import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from app.config import get_settings

settings = get_settings()
headers = {"User-Key": settings.ploomes_user_key}

for endpoint in ("Webhooks", "Webhooks@Entities", "Entities@Types"):
    r = httpx.get(
        f"{settings.ploomes_api_base}/{endpoint}",
        headers=headers,
        params={"$top": 50},
        timeout=30,
    )
    print(endpoint, r.status_code)
    if r.status_code == 200:
        data = r.json().get("value", r.json())
        if isinstance(data, list):
            for item in data[:30]:
                print(item)
        else:
            print(str(data)[:500])

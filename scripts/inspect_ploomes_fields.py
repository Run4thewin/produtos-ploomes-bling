import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from app.config import get_settings

settings = get_settings()
headers = {"User-Key": settings.ploomes_user_key}

r = httpx.get(
    f"{settings.ploomes_api_base}/Products",
    headers=headers,
    params={"$top": 1, "$expand": "OtherProperties"},
    timeout=30,
)
product = r.json().get("value", [{}])[0]
print("PRODUCT_KEYS:", sorted(product.keys()))
if product.get("OtherProperties"):
    print("SAMPLE_OTHER_PROPERTIES:")
    for op in product["OtherProperties"][:5]:
        print(op)

skip = 0
found = []
while True:
    r2 = httpx.get(
        f"{settings.ploomes_api_base}/Fields",
        headers=headers,
        params={"$top": 100, "$skip": skip},
        timeout=30,
    )
    batch = r2.json().get("value", [])
    if not batch:
        break
    for field in batch:
        key = field.get("Key") or ""
        if key.startswith("product_"):
            found.append(field)
    if len(batch) < 100:
        break
    skip += 100

print("PRODUCT_FIELDS:", len(found))
for field in found:
    print(field.get("Key"), "|", field.get("Name"), "| type", field.get("TypeId"))

import httpx
from app.config import get_settings

settings = get_settings()
headers = {"User-Key": settings.ploomes_user_key}
base = settings.ploomes_api_base

r = httpx.get(
    f"{base}/Contacts",
    headers=headers,
    params={"$top": 3, "$select": "Id,Name,TypeId,CompanyId,Email,CNPJ,CPF"},
    timeout=30,
)
print("=== Ploomes Contacts sample ===")
for c in r.json().get("value", []):
    print(c)

r2 = httpx.get(
    f"{base}/Contacts",
    headers=headers,
    params={
        "$filter": "TypeId eq 1",
        "$top": 2,
        "$select": "Id,Name,TypeId,CompanyId",
    },
    timeout=30,
)
print("\n=== Ploomes TypeId=1 (company?) ===")
for c in r2.json().get("value", []):
    print(c)

r3 = httpx.get(
    f"{base}/Contacts",
    headers=headers,
    params={
        "$filter": "CompanyId ne null",
        "$top": 3,
        "$select": "Id,Name,TypeId,CompanyId",
    },
    timeout=30,
)
print("\n=== Ploomes with CompanyId ===")
for c in r3.json().get("value", []):
    print(c)

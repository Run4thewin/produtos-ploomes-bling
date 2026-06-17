$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

& .\.venv\Scripts\pip install selenium webdriver-manager -q

Write-Host "Renovando token Bling via OAuth Selenium (projeto legado)..."
& .\.venv\Scripts\python -c @"
import sys
import os
from pathlib import Path
os.chdir(r'$Root')
sys.path.insert(0, r'$Root')
from datetime import datetime, timedelta
from app.clients.token_store import build_token_store
from app.config import get_settings
from get_autorization_token_bling import get_new_authorization_token_bling, refresh_access_token

settings = get_settings()
legacy = Path(settings.legacy_ploomes_bling_path)
if not legacy.exists():
    raise SystemExit(f'Projeto legado nao encontrado: {legacy}')
sys.path.insert(0, str(legacy))
store = build_token_store(settings.bling_tokens_path, settings.gcs_bucket)
stored = store.load()
token_info = None
if stored and stored.get('refresh_token'):
    token_info = refresh_access_token(stored['refresh_token'])
if not token_info:
    print('Refresh falhou. Abrindo navegador para OAuth...')
    token_info = get_new_authorization_token_bling()
if token_info:
    expires_at = datetime.now() + timedelta(seconds=int(token_info.get('expires_in', 3600)))
    store.save(token_info['access_token'], token_info.get('refresh_token', ''), expires_at)
    print('Token renovado com sucesso em', settings.bling_tokens_path)
else:
    raise SystemExit('Falha ao renovar token Bling.')
"@

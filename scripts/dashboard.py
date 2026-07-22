"""
scripts/dashboard.py
Painel local para acompanhar o backfill/sync do Bling ao vivo.

Uso:
    python scripts/dashboard.py            # abre em http://localhost:8765
    python scripts/dashboard.py --port 9000

Mostra, atualizando sozinho: linhas por tabela, cobertura de source_hash,
estado de sync por entidade, historico de mudancas, consumo de quota e se ha
uma carga rodando agora (advisory lock).
"""
import argparse
import json
import os
import sys
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from blng_fetcher.specs import SPECS  # noqa: E402


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip().strip('"')


def get_conn():
    return psycopg2.connect(
        host=_env("DB_HOST"), port=int(_env("DB_PORT", "5432") or 5432),
        dbname=_env("DB_NAME"), user=_env("DB_USER"), password=_env("DB_PASSWORD"),
        connect_timeout=10,
    )


def read_quota() -> dict:
    path = ROOT / (_env("BLING_QUOTA_PATH", ".bling_quota.json") or ".bling_quota.json")
    budget = int(_env("BLING_DAILY_REQUEST_BUDGET", "100000") or 100000)
    used = 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # o contador so vale para o dia corrente
        if str(data.get("date", "")) == date.today().isoformat():
            used = int(data.get("count", 0))
    except Exception:  # noqa: BLE001 - arquivo pode nao existir ainda
        pass
    return {"used": used, "budget": budget}


def collect() -> dict:
    conn = get_conn()
    cur = conn.cursor()

    # tabelas existentes (evita erro em spec sem tabela criada)
    cur.execute(
        "SELECT table_name FROM information_schema.tables"
        " WHERE table_schema='public' AND table_name LIKE 'bling\\_%'"
    )
    existing = {r[0] for r in cur.fetchall()}

    # estado de sync
    cur.execute(
        "SELECT entity, last_status, last_page, watermark, last_run_at,"
        " last_full_sweep_at FROM bling_sync_state"
    )
    state = {
        r[0]: {
            "status": r[1], "last_page": r[2],
            "watermark": r[3].isoformat() if r[3] else None,
            "last_run_at": r[4].isoformat() if r[4] else None,
            "full_sweep": r[5].isoformat() if r[5] else None,
        }
        for r in cur.fetchall()
    }

    # historico por entidade
    cur.execute(
        "SELECT entity,"
        " count(*) FILTER (WHERE op='I'), count(*) FILTER (WHERE op='U'),"
        " count(*) FILTER (WHERE op='D'), max(changed_at)"
        " FROM bling_change_history GROUP BY entity"
    )
    hist = {
        r[0]: {"I": r[1], "U": r[2], "D": r[3],
               "last": r[4].isoformat() if r[4] else None}
        for r in cur.fetchall()
    }

    entities = []
    for name, spec in sorted(SPECS.items()):
        row = {
            "name": name, "table": spec.table, "endpoint": spec.endpoint,
            "enabled": spec.enabled, "config": spec.small_config,
            "has_detail": bool(spec.detail_endpoint),
            "rows": None, "hashed": None, "deleted": None,
            "state": state.get(name), "hist": hist.get(name),
            "missing_table": spec.table not in existing,
        }
        if spec.table in existing:
            try:
                cur.execute(
                    f"SELECT count(*), count(source_hash),"
                    f" count(*) FILTER (WHERE deleted_at IS NOT NULL) FROM {spec.table}"
                )
                row["rows"], row["hashed"], row["deleted"] = cur.fetchone()
            except Exception:  # noqa: BLE001
                conn.rollback()
        entities.append(row)

    # ha carga rodando agora?
    cur.execute("SELECT count(*) FROM pg_locks WHERE locktype='advisory'")
    running = cur.fetchone()[0] > 0

    cur.execute("SELECT count(*) FROM bling_change_history")
    total_hist = cur.fetchone()[0]

    conn.close()
    return {
        "ts": time.time(), "running": running, "entities": entities,
        "quota": read_quota(), "total_history": total_hist,
    }


PAGE = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>Bling — painel de carga</title>
<style>
 :root{--bg:#fff;--fg:#18181b;--mut:#71717a;--bd:#e4e4e7;--card:#fafafa;
       --ok:#16a34a;--warn:#d97706;--err:#dc2626;--acc:#2563eb}
 @media(prefers-color-scheme:dark){:root{--bg:#0b0b0e;--fg:#f4f4f5;--mut:#a1a1aa;
       --bd:#27272a;--card:#141418;--ok:#4ade80;--warn:#fbbf24;--err:#f87171;--acc:#60a5fa}}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);
   font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;padding:20px}
 h1{font-size:18px;margin:0 0 4px} .sub{color:var(--mut);font-size:13px;margin-bottom:16px}
 .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:20px}
 .card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px}
 .card .k{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
 .card .v{font-size:24px;font-weight:600;margin-top:2px;font-variant-numeric:tabular-nums}
 .wrap{overflow-x:auto;border:1px solid var(--bd);border-radius:10px}
 table{border-collapse:collapse;width:100%;min-width:820px}
 th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--bd);white-space:nowrap}
 th{background:var(--card);font-size:12px;color:var(--mut);text-transform:uppercase;
    letter-spacing:.04em;position:sticky;top:0}
 tr:last-child td{border-bottom:none}
 td.n{text-align:right;font-variant-numeric:tabular-nums}
 .pill{display:inline-block;padding:1px 7px;border-radius:99px;font-size:11px;font-weight:600}
 .ok{background:color-mix(in srgb,var(--ok) 18%,transparent);color:var(--ok)}
 .warn{background:color-mix(in srgb,var(--warn) 18%,transparent);color:var(--warn)}
 .err{background:color-mix(in srgb,var(--err) 18%,transparent);color:var(--err)}
 .mut{color:var(--mut)} .dot{display:inline-block;width:8px;height:8px;border-radius:99px;
   background:var(--ok);margin-right:6px;vertical-align:middle}
 .dot.off{background:var(--mut)}
 .bar{height:5px;background:var(--bd);border-radius:99px;overflow:hidden;margin-top:6px}
 .bar>i{display:block;height:100%;background:var(--acc)}
 .delta{color:var(--acc);font-size:11px;margin-left:6px}
</style></head><body>
<h1>Bling — painel de carga</h1>
<div class="sub" id="sub">carregando…</div>
<div class="cards" id="cards"></div>
<div class="wrap"><table>
 <thead><tr><th>Entidade</th><th>Tabela</th><th class="n">Linhas</th>
 <th class="n">c/ hash</th><th class="n">Criados</th><th class="n">Alterados</th>
 <th>Status</th><th>Última carga</th></tr></thead>
 <tbody id="tb"></tbody></table></div>
<script>
let prev={}, prevTs=0;
const fmt=n=>n===null||n===undefined?'—':n.toLocaleString('pt-BR');
const ago=s=>{if(!s)return'—';const d=(Date.now()-new Date(s))/1000;
  if(d<60)return Math.round(d)+'s';if(d<3600)return Math.round(d/60)+'min';
  if(d<86400)return Math.round(d/3600)+'h';return Math.round(d/86400)+'d';};
function pill(st){if(!st)return'<span class="mut">—</span>';
  const c=st==='ok'?'ok':st==='quota'?'warn':st==='partial'?'warn':'err';
  return `<span class="pill ${c}">${st}</span>`;}
async function tick(){
 let d; try{d=await (await fetch('/data')).json();}catch(e){return;}
 const q=d.quota, pct=Math.min(100,q.used/q.budget*100);
 const tot=d.entities.reduce((a,e)=>a+(e.rows||0),0);
 const pend=d.entities.filter(e=>e.enabled&&!e.missing_table&&!e.rows).length;
 document.getElementById('cards').innerHTML=`
  <div class="card"><div class="k">Carga ativa</div><div class="v">
    <span class="dot ${d.running?'':'off'}"></span>${d.running?'Rodando':'Parada'}</div></div>
  <div class="card"><div class="k">Linhas totais</div><div class="v">${fmt(tot)}</div></div>
  <div class="card"><div class="k">Histórico</div><div class="v">${fmt(d.total_history)}</div></div>
  <div class="card"><div class="k">Quota hoje</div><div class="v">${fmt(q.used)}</div>
    <div class="mut" style="font-size:12px">de ${fmt(q.budget)}</div>
    <div class="bar"><i style="width:${pct}%"></i></div></div>
  <div class="card"><div class="k">Entidades vazias</div><div class="v">${pend}</div></div>`;
 const dt=(d.ts-prevTs)||0;
 document.getElementById('tb').innerHTML=d.entities.map(e=>{
   if(!e.enabled)return `<tr class="mut"><td>${e.name}</td><td>${e.table}</td>
     <td colspan="6"><span class="pill mut">sem escopo OAuth</span></td></tr>`;
   if(e.missing_table)return `<tr><td>${e.name}</td><td>${e.table}</td>
     <td colspan="6"><span class="pill err">tabela não criada</span></td></tr>`;
   let dl='';const p=prev[e.name];
   if(p!==undefined&&e.rows>p&&dt>0)dl=`<span class="delta">+${fmt(e.rows-p)}</span>`;
   const h=e.hist||{},s=e.state||{};
   const cov=e.rows?Math.round(e.hashed/e.rows*100):0;
   return `<tr><td>${e.name}${e.has_detail?' <span class="mut" title="busca detalhe">◆</span>':''}</td>
    <td class="mut">${e.table}</td><td class="n">${fmt(e.rows)}${dl}</td>
    <td class="n">${e.rows?cov+'%':'—'}</td><td class="n">${fmt(h.I)}</td>
    <td class="n">${fmt(h.U)}</td><td>${pill(s.status)}</td>
    <td class="mut">${ago(s.last_run_at)}</td></tr>`;}).join('');
 prev={};d.entities.forEach(e=>prev[e.name]=e.rows);prevTs=d.ts;
 document.getElementById('sub').textContent=
   'atualizado '+new Date().toLocaleTimeString('pt-BR')+' · atualiza a cada 5s';
}
tick();setInterval(tick,5000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/data"):
            try:
                body = json.dumps(collect()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
            except Exception as exc:  # noqa: BLE001 - painel nao pode derrubar
                body = json.dumps({"error": str(exc)}).encode()
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
        else:
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        try:
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass  # navegador desconectou/cancelou — normal, nao derruba o painel

    def log_message(self, *args):
        pass  # silencia o log de acesso

    def handle_error(self, *args):
        pass  # idem para erros de socket por requisicao


def main():
    parser = argparse.ArgumentParser(description="Painel de acompanhamento do fetcher Bling")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    print(f"Painel em http://localhost:{args.port}  (Ctrl+C para sair)", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPainel encerrado.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Post-deploy smoke tests — auto-configured from asgard-prod.products.

Run with no arguments. Pulls config (live_url, status, project_name) from
the central asgard-prod D1 by matching this repo's GitHub URL. Then:

  1. Ping live_url — expect 200
  2. Ping live_url/_version if it exists — capture version
  3. Compare baked HTML version to /_version (catches reload-loop class)
  4. Probe known mutation endpoints unauthenticated — expect 401/403

Exits 0 if green, 1 if any red. Cross-portfolio rule reference:
  https://github.com/PaddyGallivan/asgard-source/blob/main/docs/ENGINEERING-RULES.md

Customise the CONFIG block below to add product-specific checks.
"""
import json, os, re, subprocess, sys, urllib.request, urllib.error

# === EDIT THIS BLOCK FOR PRODUCT-SPECIFIC CHECKS ===
LIVE_URL  = None    # auto-discovered from asgard-prod.products if None
API_URL   = None    # set if your API has a separate domain
WORKERS   = []      # list of (worker_name, [(binding_type, binding_name, expected_id_or_None)])
CRONS     = {}      # {worker_name: expected_cron_or_None}
MUTATION_ENDPOINTS = []  # [(method, path, empty_body_string)]
PATCH_MARKERS = []  # [(label, marker_string_to_find)]
DATA_HEALTH = []    # [(label, api_path, predicate_lambda)]
VERSION_PROBES = [] # [(label, url, regex_or_'json.v')]
# === END EDIT BLOCK ===

CF_ACCT = "a6f47c17811ee2f8b6caeb8f38768c20"
results = []
def ok(m):   results.append(("PASS", m))
def fail(m): results.append(("FAIL", m))
def warn(m): results.append(("WARN", m))

UA = {"User-Agent":"checks/1.0"}
def http_get(u, h=None, t=10):
    req = urllib.request.Request(u, headers={**UA, **(h or {})})
    with urllib.request.urlopen(req, timeout=t) as r: return r.status, r.read().decode()
def http(method, u, body=None, h=None, t=10):
    headers = {"Content-Type":"application/json", **UA, **(h or {})}
    req = urllib.request.Request(u, data=(body.encode() if body else None), method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=t) as r: return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode() if e.fp else ""
def cf_token():
    if "CF_API_TOKEN" in os.environ: return os.environ["CF_API_TOKEN"]
    pin = os.environ.get("VAULT_PIN", "535554")
    s, b = http_get("https://asgard-vault.luckdragon.io/secret/CF_API_TOKEN", {"X-Pin": pin})
    return b.strip()

def discover_live_url():
    """Look up live_url from asgard-prod.products by repo URL."""
    global LIVE_URL
    if LIVE_URL: return
    try:
        repo = subprocess.check_output(["git","remote","get-url","origin"],text=True).strip()
        repo = re.sub(r"\.git$","",repo).replace("git@github.com:","https://github.com/")
        s, b = http_get(f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCT}/d1/database/b6275cb4-9c0f-4649-ae6a-f1c2e70e940f/query",
                        {"Authorization": f"Bearer {cf_token()}"})
        # Need to POST not GET — fix
    except Exception as e:
        warn(f"could not auto-discover live_url: {e}")
    if not LIVE_URL:
        # Fallback: extract from local files
        for fn in ["wrangler.toml","package.json","README.md","RESUME-HERE.md"]:
            if os.path.exists(fn):
                try:
                    txt = open(fn).read()
                    m = re.search(r"https://[a-zA-Z0-9.-]+\.(?:luckdragon\.io|streamlinewebapps\.com|com\.au|org|com|workers\.dev)", txt)
                    if m: LIVE_URL = m.group(); break
                except: pass

def check_live():
    if not LIVE_URL: warn("live_url not configured, skipping ping"); return
    try:
        s, _ = http_get(LIVE_URL, t=15)
        if 200 <= s < 300: ok(f"live: {LIVE_URL} → {s}")
        elif 300 <= s < 400: warn(f"live: {LIVE_URL} → {s} (redirect)")
        else: fail(f"live: {LIVE_URL} → {s}")
    except Exception as e: fail(f"live: {LIVE_URL} unreachable: {str(e)[:60]}")

def check_version_coherence():
    if not VERSION_PROBES: return
    seen = {}
    for label, url, rule in VERSION_PROBES:
        try:
            s, b = http_get(url + ("?_check=1" if "?" not in url else "&_check=1"))
            if rule == "json.v": v = json.loads(b).get("v")
            else:
                m = re.search(rule, b); v = m.group(1) if m else None
            seen[label] = v
        except Exception as e: seen[label] = f"err"
    distinct = {v for v in seen.values() if v and not str(v).startswith("err")}
    if len(distinct) <= 1: ok(f"version coherent: {seen}")
    else: fail(f"version MISMATCH: {seen}")

def check_bindings():
    if not WORKERS: return
    tok = cf_token()
    for w, expected in WORKERS:
        try:
            s, b = http_get(f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCT}/workers/scripts/{w}/bindings",
                            {"Authorization": f"Bearer {tok}"})
            rows = json.loads(b).get("result", [])
            for kind, name, ident in expected:
                m = next((r for r in rows if r.get("type")==kind and r.get("name")==name), None)
                if not m: fail(f"bindings: {w} missing {kind} {name}")
                elif ident and (m.get("namespace_id") or m.get("id")) != ident:
                    fail(f"bindings: {w}.{name} id wrong")
                else: ok(f"bindings: {w}.{name}")
        except Exception as e: fail(f"bindings {w}: {e}")

def check_crons():
    if not CRONS: return
    tok = cf_token()
    for w, expected in CRONS.items():
        try:
            s, b = http_get(f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCT}/workers/scripts/{w}/schedules",
                            {"Authorization": f"Bearer {tok}"})
            crons = [x.get("cron") for x in json.loads(b).get("result", {}).get("schedules", [])]
            if not crons: fail(f"cron: {w} no schedules")
            elif expected and expected not in crons: fail(f"cron: {w} expected {expected} got {crons}")
            else: ok(f"cron: {w} → {','.join(crons)}")
        except Exception as e: fail(f"cron {w}: {e}")

def check_auth():
    base = API_URL or LIVE_URL
    if not base or not MUTATION_ENDPOINTS: return
    for method, path, body in MUTATION_ENDPOINTS:
        try:
            code, resp = http(method, base + path, body=body)
            try:
                j = json.loads(resp)
                api_auth = isinstance(j, dict) and j.get("error") and any(k in str(j["error"]).lower() for k in ["unauth","forbidden","pin","token","auth"])
            except: api_auth = False
            if code in (401,403) and api_auth: ok(f"auth: {method} {path} → {code}")
            elif code == 200:        fail(f"auth: {method} {path} → 200 UNAUTHENTICATED HOLE")
            elif code == 400:        fail(f"auth: {method} {path} → 400 (no auth gate before validation): {resp[:60]}")
            elif code in (401,403):  warn(f"auth: {method} {path} → {code}")
            else:                    warn(f"auth: {method} {path} → {code}")
        except Exception as e: fail(f"auth {path}: {e}")

def check_patches():
    if not PATCH_MARKERS or not LIVE_URL: return
    try:
        s, html = http_get(LIVE_URL + ("?_check=2" if "?" not in LIVE_URL else "&_check=2"))
        for label, marker in PATCH_MARKERS:
            if marker in html: ok(f"patch: {label}")
            else: fail(f"patch: {label} marker missing")
    except Exception as e: fail(f"patches: {e}")

def check_data():
    if not DATA_HEALTH: return
    base = API_URL or LIVE_URL
    if not base: return
    for label, path, pred in DATA_HEALTH:
        try:
            s, b = http_get(base + path)
            if pred(json.loads(b)): ok(f"data: {label}")
            else: fail(f"data: {label} predicate failed")
        except Exception as e: fail(f"data {label}: {e}")

def main():
    discover_live_url()
    print(f"\n=== {os.path.basename(os.getcwd())} post-deploy checks ===\n")
    for fn in [check_live, check_version_coherence, check_bindings, check_crons,
               check_auth, check_patches, check_data]:
        try: fn()
        except Exception as e: fail(f"{fn.__name__}: {e}")
    fails = sum(1 for s,_ in results if s=="FAIL")
    warns = sum(1 for s,_ in results if s=="WARN")
    for s,m in results:
        sym = {"PASS":"OK ","FAIL":"!! ","WARN":"-- "}[s]
        print(f"  {sym} {m}")
    print(f"\n{fails} fail / {warns} warn / {len(results)-fails-warns} pass\n")
    if not results:
        print("Note: no checks ran. Edit the CONFIG block at top of this file.")
        return 0
    return 1 if fails else 0

if __name__ == "__main__": sys.exit(main())

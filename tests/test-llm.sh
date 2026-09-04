#!/usr/bin/env bash
# Tests de ghost-llm contre un faux serveur LM Studio (API compatible OpenAI).
# Prouve que le client parle vraiment le protocole : liste des modèles,
# auto-détection de Dolphin, streaming, et erreur claire si l'endpoint est mort.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"; [[ -n "${MOCK:-}" ]] && kill "$MOCK" 2>/dev/null' EXIT
pass=0; fail=0
ck() { if [[ "$2" == "0" ]]; then echo "  OK  $1"; pass=$((pass+1));
       else echo "  KO  $1${3:+ — $3}"; fail=$((fail+1)); fi; }

cat > "$TMP/mock.py" <<'PY'
import json, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
MODELS = ["text-embedding-nomic", "dolphin-2.9.3-mistral-7b", "qwen2.5-3b"]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            b = json.dumps({"data":[{"id":m} for m in MODELS]}).encode()
            self.send_response(200); self.send_header("Content-Length",str(len(b)))
            self.end_headers(); self.wfile.write(b)
        else: self.send_error(404)
    def do_POST(self):
        n=int(self.headers.get("Content-Length","0"))
        req=json.loads(self.rfile.read(n) or b"{}")
        u=next((m["content"] for m in reversed(req.get("messages",[])) if m["role"]=="user"),"")
        self.send_response(200); self.send_header("Content-Type","text/event-stream"); self.end_headers()
        for tok in f"[{req.get('model')}] echo {u}".split(" "):
            self.wfile.write(f"data: {json.dumps({'choices':[{'delta':{'content':tok+' '}}]})}\n\n".encode()); self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()
ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
PY

# port peu banal pour éviter les collisions
PORT=$(( 20000 + RANDOM % 20000 ))
python3 "$TMP/mock.py" "$PORT" >/dev/null 2>&1 & MOCK=$!
# attendre que le port réponde
for _ in $(seq 1 40); do
  python3 -c "import socket,sys;s=socket.socket();s.settimeout(0.2);sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)" && break
  sleep 0.1
done

export GHOSTBOARD_LLM_BASE="http://127.0.0.1:$PORT/v1" NO_COLOR=1

echo "ghost-llm — protocole LM Studio (mock)"
out="$("$ROOT/tools/ghost-llm" --check 2>&1)"
grep -q "joignable" <<<"$out" && ck "endpoint joignable" 0 || ck "endpoint joignable" 1 "$out"
grep -q "dolphin-2.9.3-mistral-7b  (actif)" <<<"$out" \
  && ck "Dolphin auto-détecté comme modèle actif" 0 || ck "auto-détection Dolphin" 1 "$out"

models="$("$ROOT/tools/ghost-llm" --models 2>&1)"
[[ "$(wc -l <<<"$models")" == "3" ]] && ck "--models liste les 3 modèles" 0 || ck "--models" 1

ans="$("$ROOT/tools/ghost-llm" "salut" 2>&1)"
grep -q "dolphin" <<<"$ans" && grep -q "echo salut" <<<"$ans" \
  && ck "one-shot streame via Dolphin" 0 || ck "one-shot" 1 "$ans"

piped="$(echo "par pipe" | "$ROOT/tools/ghost-llm" - 2>&1)"
grep -q "echo par pipe" <<<"$piped" && ck "lecture de stdin (pipe)" 0 || ck "pipe" 1 "$piped"

forced="$("$ROOT/tools/ghost-llm" -m qwen2.5-3b "x" 2>&1)"
grep -q "qwen2.5-3b" <<<"$forced" && ck "-m force un autre modèle" 0 || ck "-m" 1 "$forced"

echo
echo "ghost-llm — endpoint mort"
dead="$(GHOSTBOARD_LLM_BASE='http://127.0.0.1:1/v1' "$ROOT/tools/ghost-llm" --check 2>&1)"; rc=$?
[[ "$rc" -ne 0 ]] && grep -qi "injoignable" <<<"$dead" \
  && ck "erreur claire + code non nul quand LM Studio est absent" 0 \
  || ck "erreur endpoint mort" 1 "rc=$rc $dead"

echo
echo "$([[ $fail -eq 0 ]] && echo SUCCÈS || echo ÉCHEC) : $pass réussi(s), $fail échec(s)"
exit $(( fail > 0 ))

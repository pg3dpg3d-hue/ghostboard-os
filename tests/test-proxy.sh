#!/usr/bin/env bash
# Teste ghost-llm-proxy : requêtes au FORMAT ANTHROPIC en entrée, LM Studio
# (OpenAI) simulé en sortie. Prouve la traduction dans les deux sens sans
# Claude Code ni LM Studio réels.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
MOCK=""; PROXY=""
cleanup(){ [[ -n "$MOCK" ]] && kill "$MOCK" 2>/dev/null; [[ -n "$PROXY" ]] && kill "$PROXY" 2>/dev/null; rm -rf "$TMP"; }
trap cleanup EXIT
pass=0; fail=0
ck(){ if [[ "$2" == "0" ]]; then echo "  OK  $1"; pass=$((pass+1)); else echo "  KO  $1${3:+ — $3}"; fail=$((fail+1)); fi; }

# --- mock LM Studio (OpenAI) ---
cat > "$TMP/mock.py" <<'PY'
import json,sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class H(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"
    def log_message(self,*a): pass
    def _send(self, code, body, ctype="application/json"):
        b=body if isinstance(body,bytes) else body.encode()
        self.send_response(code); self.send_header("Content-Type",ctype)
        self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._send(200, json.dumps({"data":[{"id":"dolphin-2.9-mistral-7b"}]}))
        else: self.send_error(404)
    def do_POST(self):
        n=int(self.headers.get("Content-Length","0")); req=json.loads(self.rfile.read(n) or b"{}")
        wants_tool = bool(req.get("tools")) and "use_tool" in json.dumps(req.get("messages",[]))
        if req.get("stream"):
            self.send_response(200); self.send_header("Content-Type","text/event-stream"); self.end_headers()
            for tok in ["Bonjour ","depuis ","le ","modele ","local"]:
                self.wfile.write(f"data: {json.dumps({'choices':[{'delta':{'content':tok}}]})}\n\n".encode()); self.wfile.flush()
            self.wfile.write(f"data: {json.dumps({'choices':[{'delta':{},'finish_reason':'stop'}],'usage':{'completion_tokens':5}})}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()
            return
        if wants_tool:
            msg={"role":"assistant","content":None,"tool_calls":[{"id":"call_1","type":"function",
                 "function":{"name":"get_weather","arguments":json.dumps({"city":"Paris"})}}]}
            self._send(200, json.dumps({"choices":[{"message":msg,"finish_reason":"tool_calls"}],
                       "usage":{"prompt_tokens":10,"completion_tokens":7}}))
        else:
            self._send(200, json.dumps({"choices":[{"message":{"role":"assistant","content":"Reponse locale."},
                       "finish_reason":"stop"}],"usage":{"prompt_tokens":8,"completion_tokens":3}}))
ThreadingHTTPServer(("127.0.0.1",int(sys.argv[1])),H).serve_forever()
PY

MPORT=$((20000+RANDOM%10000)); PPORT=$((30000+RANDOM%10000))
python3 "$TMP/mock.py" "$MPORT" >/dev/null 2>&1 & MOCK=$!
GHOSTBOARD_LLM_BASE="http://127.0.0.1:$MPORT/v1" python3 "$ROOT/tools/ghost-llm-proxy" \
  --port "$PPORT" --lm "http://127.0.0.1:$MPORT/v1" >/dev/null 2>&1 & PROXY=$!
for _ in $(seq 1 50); do
  python3 -c "import socket,sys;s=socket.socket();s.settimeout(.2);sys.exit(0 if s.connect_ex(('127.0.0.1',$PPORT))==0 else 1)" && break; sleep 0.1
done
A="http://127.0.0.1:$PPORT"

echo "ghost-llm-proxy — GET /v1/models (forme Anthropic)"
m="$(curl -s "$A/v1/models")"
python3 -c "import json,sys;d=json.load(sys.stdin);assert d['data'][0]['id'] and 'display_name' in d['data'][0]" <<<"$m" 2>/dev/null
ck "modèle exposé en forme Anthropic" $?

echo
echo "ghost-llm-proxy — POST /v1/messages non-streaming"
r="$(curl -s "$A/v1/messages" -H 'content-type: application/json' -H 'x-api-key: dummy' \
  -d '{"model":"claude-x","max_tokens":100,"system":"sois bref","messages":[{"role":"user","content":"salut"}]}')"
python3 - "$r" <<'PY'
import json,sys
d=json.loads(sys.argv[1])
assert d["type"]=="message" and d["role"]=="assistant", d
assert d["content"][0]["type"]=="text" and "locale" in d["content"][0]["text"], d
assert d["stop_reason"]=="end_turn", d
assert d["usage"]["input_tokens"]==8 and d["usage"]["output_tokens"]==3, d
PY
ck "réponse traduite au format Anthropic (message/text/stop/usage)" $?

echo
echo "ghost-llm-proxy — POST /v1/messages streaming (SSE Anthropic)"
s="$(curl -s -N "$A/v1/messages" -H 'content-type: application/json' \
  -d '{"model":"claude-x","max_tokens":100,"stream":true,"messages":[{"role":"user","content":"salut"}]}')"
grep -q 'event: message_start' <<<"$s" && ck "événement message_start" 0 || ck "message_start" 1
grep -q 'event: content_block_delta' <<<"$s" && grep -q 'text_delta' <<<"$s" \
  && ck "content_block_delta text_delta (tokens streamés)" 0 || ck "text_delta" 1
grep -q 'event: message_stop' <<<"$s" && ck "événement message_stop" 0 || ck "message_stop" 1
# le texte concaténé doit se reconstituer
txt="$(python3 - "$s" <<'PY'
import sys,json,re
out=[]
for line in sys.argv[1].splitlines():
    if line.startswith("data:"):
        try: o=json.loads(line[5:].strip())
        except: continue
        if o.get("type")=="content_block_delta" and o["delta"].get("type")=="text_delta":
            out.append(o["delta"]["text"])
print("".join(out))
PY
)"
[[ "$txt" == "Bonjour depuis le modele local" ]] && ck "le texte streamé se reconstitue exactement" 0 || ck "reconstitution" 1 "[$txt]"

echo
echo "ghost-llm-proxy — appel d'outil (tool_use)"
t="$(curl -s "$A/v1/messages" -H 'content-type: application/json' \
  -d '{"model":"claude-x","max_tokens":100,"messages":[{"role":"user","content":"use_tool please"}],"tools":[{"name":"get_weather","description":"w","input_schema":{"type":"object","properties":{"city":{"type":"string"}}}}]}')"
python3 - "$t" <<'PY'
import json,sys
d=json.loads(sys.argv[1])
tu=[b for b in d["content"] if b["type"]=="tool_use"]
assert tu, ("pas de tool_use", d)
assert tu[0]["name"]=="get_weather" and tu[0]["input"]=={"city":"Paris"}, tu
assert d["stop_reason"]=="tool_use", d
PY
ck "tool_calls OpenAI -> tool_use Anthropic (nom+input+stop_reason)" $?

echo
echo "$([[ $fail -eq 0 ]] && echo SUCCÈS || echo ÉCHEC) : $pass réussi(s), $fail échec(s)"
exit $(( fail > 0 ))

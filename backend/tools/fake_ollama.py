"""Fake Ollama: /api/tags, /api/ps, /api/chat (streaming). Records every request's num_ctx."""
import json, threading, time, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = []   # (path, num_ctx, keep_alive, think, format, user_text)
MODE = {"reply": "پاسخ آزمایشی مدل.", "delay": 0.0, "fail": None, "planner": None}

class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _json(self, code, obj):
        b=json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.startswith("/api/tags"): return self._json(200,{"models":[{"name":"qwen3.5:4b"}]})
        if self.path.startswith("/api/ps"): return self._json(200,{"models":[{"name":"qwen3.5:4b"}]})
        self._json(404,{})
    def do_POST(self):
        n=int(self.headers.get("Content-Length",0)); body=json.loads(self.rfile.read(n) or b"{}")
        if self.path!="/api/chat": return self._json(404,{})
        opts=body.get("options",{}); msgs=body.get("messages",[])
        LOG.append((opts.get("num_ctx"), body.get("keep_alive"), body.get("think"), body.get("format"), msgs[-1]["content"], len(msgs)))
        if MODE["fail"]=="400think" and body.get("think") is True:
            return self._json(400,{"error":"\"qwen\" does not support thinking"})
        if MODE["fail"]=="500": return self._json(500,{"error":"boom"})
        time.sleep(MODE["delay"])
        text = MODE["planner"] if body.get("format")=="json" and MODE["planner"] is not None else MODE["reply"]
        self.send_response(200); self.send_header("Content-Type","application/x-ndjson"); self.end_headers()
        if body.get("stream") is False:
            self.wfile.write(json.dumps({"message":{"content":text},"done":True,"load_duration":10**9}).encode()); return
        if body.get("think"):
            self.wfile.write((json.dumps({"message":{"thinking":"hmm"},"done":False})+"\n").encode())
        for i in range(0,len(text),6):
            self.wfile.write((json.dumps({"message":{"content":text[i:i+6]},"done":False})+"\n").encode()); self.wfile.flush(); time.sleep(0.01)
        self.wfile.write((json.dumps({"message":{"content":""},"done":True,"load_duration":2*10**8,"eval_count":9})+"\n").encode())

def start(port=11434):
    srv=ThreadingHTTPServer(("127.0.0.1",port),H); threading.Thread(target=srv.serve_forever,daemon=True).start(); return srv

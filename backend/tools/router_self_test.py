"""Smartis 2.13 router self-test.

Runs the REAL router / chat / planner / executor against a FAKE Ollama server
(port 11999, so a real Ollama on 11434 is never touched) and a fake tool
executor (nothing is opened, deleted or shut down). Verifies:
command-vs-chat separation, confirmation flow, one shared num_ctx,
streaming/cancel/error handling.
"""
import sys, os, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
os.environ["OLLAMA_URL"] = "http://127.0.0.1:11999"; os.environ["SMARTIS_NOISE_GATE"] = "relaxed"
import fake_ollama as fo
srv = fo.start(11999)
from agent import router, executor
from agent.context_memory import memory
import agent.tools as tools

executed=[]
def fake_exec(name,args):
    executed.append((name,args)); return {"ok":True,"speak":f"{name} done"}
executor.execute_tool = fake_exec          # no real OS actions in the sandbox

PASS=FAIL=0
def check(name,cond,extra=""):
    global PASS,FAIL
    if cond: PASS+=1; print(f"  PASS  {name}")
    else: FAIL+=1; print(f"  FAIL  {name}  {extra}")

def reset(): executed.clear(); fo.LOG.clear(); executor.clear_pending_confirmation(); memory.reset()

print("== 1. chat goes to Ollama, never executes")
reset()
for q in ["درود خوبی","تفاوت CPU و GPU چیه؟","what is knowledge?","چطور کروم رو باز کنم؟","how do I restart my router?","I could not sleep last night","ایلان ماسک کیه"]:
    r=router.handle_input(q,None,source="text")
    check(f"chat: {q}", r["mode"]=="chat" and r["plan"]["reply"] and not executed, f"{r['mode']} {executed}")
check("all chat requests share one num_ctx", len({x[0] for x in fo.LOG})==1, str({x[0] for x in fo.LOG}))
check("keep_alive=-1 on all", all(x[1]==-1 for x in fo.LOG))

print("== 2. commands execute, Ollama NOT called")
reset()
for q,tool in [("گوگل رو باز کن","open_chrome_url"),("صدا 20 درصد","system_volume_set"),("هوای کرج","get_weather"),("ساعت چنده؟","get_time_date"),("آهنگ بعدی","media_next"),("open chrome","open_application")]:
    executed.clear(); fo.LOG.clear()
    r=router.handle_input(q,None,source="text")
    check(f"cmd: {q} -> {tool}", r["mode"]=="command" and executed and executed[0][0]==tool and not fo.LOG, f"{r['mode']} {executed} llm={len(fo.LOG)}")

print("== 3. open Edge false positive (word 'knowledge')")
reset(); r=router.handle_input("open knowledge base please",None,source="text")
check("'knowledge' does not open Edge", not any(a[0]=="open_application" for a in executed), str(executed))

print("== 4. confirmation flow")
reset()
r=router.handle_input("سیستم رو خاموش کن",None,source="text")
check("shutdown asks confirmation", r["needs_confirmation"] and not executed and router.pending_confirmation(), str(r))
check("question text is specific", "خاموش" in r["plan"]["reply"], r["plan"]["reply"])
fo.LOG.clear()
r=router.handle_input("بله",None,source="text")
check("'بله' executes pending as command, not chat", r["mode"]=="command" and executed==[("shutdown_windows",{})] and not fo.LOG, f"{r['mode']} {executed} {len(fo.LOG)}")
check("pending cleared", not router.pending_confirmation())

reset(); router.handle_input("restart",None,source="text")
r=router.handle_input("لغو",None,source="text")
check("cancel works, nothing executed", r["mode"]=="command" and not executed and not router.pending_confirmation())

reset(); router.handle_input("پوشه Test رو پیدا کن و حذفش کن",None,source="text")
check("delete_named now needs confirmation", router.pending_confirmation() and not executed, str(executed))
r=router.handle_input("ساعت چنده",None,source="text")
check("other utterance drops pending (fail-safe) and is processed", not router.pending_confirmation() and not executed or executed==[("get_time_date",{})], str(executed))
check("deleted nothing", not any(a[0].startswith("delete") for a in executed))

reset(); router.handle_input("کروم رو ببند",None,source="text")
check("close app asks confirmation", router.pending_confirmation() and not executed)
r=router.handle_input("آره",None,source="voice")
check("voice yes confirms", executed and executed[0][0]=="close_application", str(executed))

reset(); r=router.handle_input("how do I restart my router?",None,source="text")
check("'how do I restart' does not queue power action", not router.pending_confirmation() and r["mode"]=="chat")

print("== 5. cancel word 'cancel shutdown' not treated as shutdown")
reset(); r=router.handle_input("cancel shutdown",None,source="text")
check("cancel_shutdown tool", executed and executed[0][0]=="cancel_shutdown", str(executed))

print("== 6. planner (command-shaped, not deterministic)")
reset(); fo.MODE["planner"]='{"reply":"ok","actions":[{"tool":"open_windows_settings","args":{}}],"needs_confirmation":false}'
r=router.handle_input("لطفا یه بار ببر تنظیمات رو برام باز بذار",None,source="text")
check("planner plan executed", r["mode"]=="command" and r["provider"]=="ollama-planner" and executed, f"{r['mode']} {r['provider']} {executed}")
fo.MODE["planner"]='{"reply":"","actions":[{"tool":"hack_the_planet","args":{}}],"needs_confirmation":false}'
reset(); r=router.handle_input("اون فایل رو باز بذار برام",None,source="text")
check("unknown tool from planner rejected -> chat", r["mode"]=="chat" and not executed, f"{r['mode']} {executed}")
fo.MODE["planner"]=None

print("== 7. thinking mode + fallback + errors")
reset(); r=router.handle_input("پایتخت فرانسه کجاست؟",None,source="text",thinking=True)
check("thinking works", r["mode"]=="chat" and r["thinking"] and r["plan"]["reply"], str(r))
reset(); fo.MODE["fail"]="400think"; r=router.handle_input("سلام",None,source="text",thinking=True)
check("think=400 retried without think", r["plan"]["reply"] and any(x[2] is None for x in fo.LOG) , str(fo.LOG))
fo.MODE["fail"]="500"; r=router.handle_input("سلام",None,source="text")
check("HTTP 500 -> human error + provider chat-error", r["provider"]=="chat-error" and r["plan"]["reply"], str(r))
fo.MODE["fail"]=None

print("== 8. history is used as real messages")
reset(); router.handle_input("اسم من علی است",None,source="text"); fo.LOG.clear()
router.handle_input("اسم من چی بود؟",None,source="text")
check("second request carries previous turn (msgs>2)", fo.LOG and fo.LOG[-1][5]>=4, str(fo.LOG))

print("== 9. cancel mid-stream")
import threading
reset(); fo.MODE["reply"]="x"*3000; fo.MODE["delay"]=0.0
from agent import chat
res={}
def go(): res["r"]=router.handle_input("یه متن خیلی بلند بنویس",None,source="text",request_id="req1")
t=threading.Thread(target=go); t.start(); time.sleep(0.15); chat.cancel_request("req1"); t.join(5)
check("cancelled request returns cancelled", res.get("r",{}).get("cancelled") is True, str(res.get("r",{}).get("provider")))
fo.MODE["reply"]="پاسخ آزمایشی مدل."

print("== 10. voice: echo/noise gates")
reset(); r=router.handle_input("اوه",None,source="voice")
check("noise discarded", r.get("ignored") is True)
r=router.handle_input("بله",None,source="text")  # no pending -> chat
check("bare yes without pending -> chat", r["mode"]=="chat")

print("== 11. unreachable Ollama")
srv.shutdown(); srv.server_close(); time.sleep(0.2)
reset(); r=router.handle_input("سلام",None,source="text")
check("offline -> clear message, no crash", r["provider"]=="chat-error" and "Ollama" in r["plan"]["reply"], r["plan"]["reply"])

print(f"\nRESULT: {PASS} passed, {FAIL} failed"); sys.exit(1 if FAIL else 0)

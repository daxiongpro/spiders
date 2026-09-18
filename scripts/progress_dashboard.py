#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
抖音收藏文案整理 · 实时进度看板（下载/转写分栏 + 单条状态）
本地 http 服务：GET / 返回看板页面，GET /api/status 返回实时 JSON。
实时扫描：各分类 已下载(本地mp4)/已转写(md成品)/清单总数 + 流水线 _realtime.json 单条状态。
"""
import os, re, json, glob, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer

SP  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根 spiders
OUT = os.environ.get("DOUYIN_OUT") or os.path.join(
    os.path.dirname(SP), "抖音收藏文案整理")
TA  = os.path.join(OUT, "_temp_audio")
LOG = os.path.join(SP, "_pipeline.log")
RT  = os.path.join(SP, "_realtime.json")
PORT = 8137

CAT_ORDER = ["搞钱·事业","投资·理财","求职·职场","学习·成长","探店·吃喝",
             "家庭·婚姻","生活·出行","娱乐·休闲","未分类"]

_lock = threading.Lock()

def compute_status():
    # 1) 清单：各分类总数 + seq->cat
    total_by_cat, seq_cat = {}, {}
    for jf in glob.glob(os.path.join(SP, "config", "list_*.json")):
        try:
            data = json.load(open(jf, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for it in data:
            if isinstance(it, dict):
                seq = it.get("序号"); cat = it.get("新分类", "")
                if seq is not None and cat:
                    total_by_cat[cat] = total_by_cat.get(cat, 0) + 1
                    seq_cat[seq] = cat
    # 2) 已转写（md 成品，含【转写失败】/【视频失效】）
    done_by_cat = {}
    for cat in total_by_cat:
        d = os.path.join(OUT, cat)
        done_by_cat[cat] = len(glob.glob(os.path.join(d, "*.md"))) if os.path.isdir(d) else 0
    # 3) 已下载（本地 _temp_audio 有 mp4，含已转写+待转写）
    down_by_cat = {}
    for mp in glob.glob(os.path.join(TA, "seq*_*.mp4")):
        m = re.search(r"seq(\d+)_", os.path.basename(mp))
        if not m:
            continue
        c = seq_cat.get(int(m.group(1)))
        if c:
            down_by_cat[c] = down_by_cat.get(c, 0) + 1
    # 4) 总进度
    total_all = sum(total_by_cat.values())
    done_all  = sum(done_by_cat.values())
    down_all  = sum(down_by_cat.values())
    # 5) 实时单条状态
    rt = {}
    if os.path.exists(RT):
        try:
            rt = json.load(open(RT, encoding="utf-8"))
        except Exception:
            rt = {}
    phase = rt.get("phase", "idle")
    category = rt.get("category", "")
    fetch_plan = rt.get("fetch_plan", [])
    fetch_done = rt.get("fetch_done", 0)
    fetch_round = rt.get("fetch_round", 0)
    titems = rt.get("transcribe_items", {})
    auth_error = rt.get("auth_error", False)
    # 当前正在下载的那条
    fetch_current = fetch_plan[fetch_done] if (phase == "fetch" and fetch_done < len(fetch_plan)) else None
    # 转写单条归类
    transcribing = [{"seq": k, **v} for k, v in titems.items()]
    in_prog = [x for x in transcribing if x["status"] in ("upload", "minutes", "polling")]
    ok_cnt = sum(1 for x in transcribing if x["status"] == "ok")
    fail_cnt = sum(1 for x in transcribing if x["status"] == "fail")
    # 6) 流水线最近日志 + 总体阶段文案
    last_logs, overall = [], "空闲"
    if os.path.exists(LOG):
        lines = [l for l in open(LOG, encoding="utf-8").read().splitlines() if l.strip()]
        last_logs = lines[-14:]
        last = lines[-1] if lines else ""
        if "PIPELINE_DONE" in last:
            overall = "✅ 全部完成"
        elif "PIPELINE_HALT_AUTH" in last or auth_error:
            overall = "⚠️ 飞书授权失效，已暂停（需重新授权）"
        elif phase == "fetch":
            overall = "⬇️ 下载中"
        elif phase == "transcribe":
            overall = "🎙️ 转写中"
        elif category:
            overall = "处理中"
    # 7) 分类列表
    cats = []
    for c in CAT_ORDER:
        if c in total_by_cat:
            t = total_by_cat[c]; d = done_by_cat.get(c, 0); w = down_by_cat.get(c, 0)
            cats.append({"cat": c, "total": t, "done": d, "down": w,
                         "pct": round(100.0*d/t, 1) if t else 100.0,
                         "active": c == category})
    for c in total_by_cat:
        if c not in CAT_ORDER:
            t = total_by_cat[c]; d = done_by_cat.get(c, 0); w = down_by_cat.get(c, 0)
            cats.append({"cat": c, "total": t, "done": d, "down": w,
                         "pct": round(100.0*d/t, 1) if t else 100.0,
                         "active": c == category})
    return {
        "total_all": total_all, "done_all": done_all, "down_all": down_all,
        "pct_all": round(100.0*done_all/total_all, 1) if total_all else 0.0,
        "phase": phase, "category": category, "overall": overall,
        "fetch_round": fetch_round, "fetch_plan": fetch_plan, "fetch_done": fetch_done,
        "fetch_current": fetch_current, "auth_error": auth_error,
        "transcribing": transcribing, "in_prog": len(in_prog),
        "ok_cnt": ok_cnt, "fail_cnt": fail_cnt,
        "cats": cats, "logs": last_logs, "updated": time.strftime("%H:%M:%S"),
    }

HTML = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>抖音收藏文案整理 · 实时进度</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
       background:#f5f7fa;color:#1f2d3d;padding:22px}
  h1{font-size:21px;margin:0 0 4px}.sub{color:#7a8aa0;font-size:13px;margin-bottom:16px}
  .wrap{max-width:900px;margin:0 auto}
  .top{display:flex;gap:20px;align-items:center;background:#fff;border-radius:14px;
       padding:20px 24px;box-shadow:0 2px 10px rgba(0,0,0,.05);margin-bottom:16px}
  .ring{--p:0;width:118px;height:118px;border-radius:50%;flex:0 0 auto;
        background:conic-gradient(#2f7cf6 calc(var(--p)*1%),#e6ebf2 0);
        display:flex;align-items:center;justify-content:center}
  .ring .inner{width:90px;height:90px;border-radius:50%;background:#fff;
        display:flex;flex-direction:column;align-items:center;justify-content:center}
  .ring .pct{font-size:25px;font-weight:700;color:#2f7cf6}
  .ring .num{font-size:12px;color:#7a8aa0}
  .meta{flex:1}.meta .phase{font-size:18px;font-weight:600;margin-bottom:6px}
  .meta .row{font-size:13px;color:#52617a;line-height:1.9}
  .badge{display:inline-block;background:#eaf2ff;color:#2f7cf6;border-radius:6px;
         padding:2px 8px;font-size:12px;margin-right:6px}
  .badge.g{background:#e8f8f0;color:#22b07d}
  .card{background:#fff;border-radius:14px;padding:16px 20px;
        box-shadow:0 2px 10px rgba(0,0,0,.05);margin-bottom:16px}
  .card h2{font-size:15px;margin:0 0 12px;color:#33445a}
  .item{margin-bottom:12px}
  .item .lab{display:flex;justify-content:space-between;font-size:13px;margin-bottom:5px}
  .item .lab .nm{font-weight:600}.item .lab .nm.active{color:#2f7cf6}
  .item .lab .v{color:#7a8aa0}
  .bars{display:flex;gap:6px;height:10px}
  .bars>i{display:block;height:100%;border-radius:5px;transition:width .6s ease}
  .b-down{background:#cbd5e1}.b-done{background:linear-gradient(90deg,#2f7cf6,#5aa0ff)}
  .legend{font-size:12px;color:#9aa7b8;margin-top:8px}
  .legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin:0 4px 0 12px;vertical-align:-1px}
  .stage{font-size:14px;line-height:1.8}
  .stage .big{font-size:16px;font-weight:600;margin-bottom:6px}
  .seqgrid{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
  .seq{font-size:12px;border-radius:8px;padding:6px 10px;background:#f3f6fa;
       border:1px solid #e6ebf2;min-width:96px}
  .seq b{display:block;font-size:13px;margin-bottom:2px}
  .seq .st{font-weight:600}
  .st.upload{color:#b7791f}.st.minutes{color:#7a4fd6}.st.polling{color:#2f7cf6}
  .st.ok{color:#22b07d}.st.fail{color:#e0533d}
  .dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px;vertical-align:1px}
  .logs{background:#0f1722;color:#9fe6c2;border-radius:10px;padding:14px 16px;
        font-family:Consolas,Menlo,monospace;font-size:12px;line-height:1.7;
        max-height:210px;overflow:auto;white-space:pre-wrap}
  .foot{text-align:center;color:#9aa7b8;font-size:12px;margin-top:6px}
</style></head><body><div class="wrap">
  <h1>抖音收藏文案整理 · 实时进度</h1>
  <div class="sub">本地自动刷新（每 4 秒）· 数据源：成品目录 + 流水线逐条状态</div>
  <div class="top">
    <div class="ring" id="ring"><div class="inner">
      <div class="pct" id="pct">0%</div><div class="num" id="num">0/0</div></div></div>
    <div class="meta">
      <div class="phase" id="phase">加载中…</div>
      <div class="row" id="row1"></div>
      <div class="row" id="row2"></div>
    </div>
  </div>

  <div class="card"><h2>当前这一步在干啥（单条实时）</h2>
    <div class="stage" id="stage">加载中…</div>
    <div class="seqgrid" id="seqgrid"></div>
  </div>

  <div class="card"><h2>各分类：下载 / 转写 进度</h2>
    <div id="cats"></div>
    <div class="legend"><i class="b-down"></i>已下载(本地视频) <i class="b-done"></i>已转写(成品)</div>
  </div>

  <div class="card"><h2>流水线最近日志</h2><div class="logs" id="logs"></div></div>
  <div class="foot" id="foot"></div>
</div>
<script>
const ST={upload:["上传中","upload"],minutes:["妙记创建","minutes"],polling:["轮询中","polling"],ok:["完成","ok"],fail:["失败","fail"]};
async function load(){
  try{
    const r=await fetch('/api/status');const s=await r.json();
    document.getElementById('ring').style.setProperty('--p',s.pct_all);
    document.getElementById('pct').textContent=s.pct_all+'%';
    document.getElementById('num').textContent=s.done_all+'/'+s.total_all;
    document.getElementById('phase').textContent=s.overall;
    document.getElementById('row1').innerHTML=
      '<span class="badge">已下载</span>'+s.down_all+' 条　'+
      '<span class="badge g">已转写</span>'+s.done_all+' 条　'+
      '共 '+s.total_all+' 条';
    document.getElementById('row2').textContent='剩余 '+(s.total_all-s.done_all)+' 条未完成　·　更新于 '+s.updated;
    // 当前阶段
    let st='';
    if(s.phase==='fetch'){
      const cur=s.fetch_current? ('序号 '+s.fetch_current):'—';
      st='<div class="big">⬇️ 下载中 · '+s.category+'（第'+(s.fetch_round+1)+'轮）</div>'+
         '本轮计划 '+s.fetch_plan.length+' 条，已下载完成 '+s.fetch_done+' 条，正在下载：<b>'+cur+'</b>';
    }else if(s.phase==='transcribe'){
      st='<div class="big">🎙️ 转写中 · '+s.category+'</div>'+
         '本轮 '+s.transcribing.length+' 条：进行中 '+s.in_prog+' · 完成 '+s.ok_cnt+' · 失败 '+s.fail_cnt;
    }else if(s.overall.indexOf('完成')>=0){
      st='<div class="big">'+s.overall+'</div>全部分类已处理完毕。';
    }else if(s.overall.indexOf('授权')>=0){
      st='<div class="big">'+s.overall+'</div>请在飞书重新授权后让我重跑流水线。';
    }else{
      st='<div class="big">'+s.overall+'</div>'+(s.category?('当前分类：'+s.category):'');
    }
    document.getElementById('stage').innerHTML=st;
    // 单条网格
    const g=document.getElementById('seqgrid');g.innerHTML='';
    (s.transcribing||[]).forEach(x=>{
      const m=ST[x.status]||[x.status,x.status];
      g.insertAdjacentHTML('beforeend',
        '<div class="seq"><b>序号 '+x.seq+'</b>'+
        '<span class="st '+m[1]+'"><span class="dot" style="background:'+
        (m[1]==='ok'?'#22b07d':m[1]==='fail'?'#e0533d':m[1]==='polling'?'#2f7cf6':m[1]==='minutes'?'#7a4fd6':'#b7791f')+
        '"></span>'+m[0]+'</span></div>');
    });
    if((s.transcribing||[]).length===0 && s.phase==='fetch' && s.fetch_current){
      g.insertAdjacentHTML('beforeend','<div class="seq"><b>序号 '+s.fetch_current+'</b>'+
        '<span class="st upload"><span class="dot" style="background:#b7791f"></span>下载中</span></div>');
    }
    // 分类
    const c=document.getElementById('cats');c.innerHTML='';
    s.cats.forEach(x=>{
      const pct=x.pct;const act=x.active?' active':'';
      const dw=Math.min(100,Math.round(100.0*x.down/x.total))||0;
      c.insertAdjacentHTML('beforeend',
        '<div class="item"><div class="lab"><span class="nm'+act+'">'+x.cat+
        (x.active?' ◀ 进行中':'')+'</span><span class="v">转写 '+x.done+'/'+x.total+
        '（'+pct+'%）· 已下载 '+x.down+'</span></div>'+
        '<div class="bars"><i class="b-down" style="width:'+dw+'%"></i>'+
        '<i class="b-done" style="width:'+pct+'%"></i></div></div>');
    });
    document.getElementById('logs').textContent=(s.logs||[]).join('\n')||'（暂无日志）';
    document.getElementById('foot').textContent='每 4 秒自动刷新 · 端口 8137';
  }catch(e){document.getElementById('phase').textContent='读取状态失败：'+e;}
}
load();setInterval(load,4000);
</script></body></html>"""

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/status"):
            with _lock:
                data = compute_status()
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    def log_message(self, *a):
        pass

if __name__ == "__main__":
    srv = HTTPServer(("127.0.0.1", PORT), H)
    print("progress dashboard on http://127.0.0.1:%d" % PORT, flush=True)
    srv.serve_forever()

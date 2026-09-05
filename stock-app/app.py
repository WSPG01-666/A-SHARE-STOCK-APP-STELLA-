#!/usr/bin/env python3
"""STELLAR A-Share Terminal - Flask backend"""
import json, os, urllib.request, re, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# Ensure the project root is in Python path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import Flask, jsonify, request, render_template
from strategies import StockStrategyEngine, MinuteT0Engine
from simulation import SimulationEngine

WATCHLIST_FILE = os.path.join(PROJECT_ROOT, "watchlist.json")
engine = StockStrategyEngine()
t0_engine = MinuteT0Engine()
sim = SimulationEngine()

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []

def save_watchlist(data):
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

app = Flask(__name__)

HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

POPULAR = {
    "sh000001": "SSE Index", "sh000300": "CSI 300", "sz399001": "SZSE Component",
    "sz399006": "ChiNext", "sh000688": "STAR 50", "sh000016": "SSE 50",
}
INDEX_CODES = ["sh000001","sh000300","sz399001","sz399006","sh000688","sh000016","sh000905"]
INDEX_NAMES = {
    "sh000001":"SSE","sh000300":"CSI300","sz399001":"SZSE","sz399006":"ChiNext",
    "sh000688":"STAR50","sh000016":"SSE50","sh000905":"CSI500",
}
KLINE_TYPE = {"day":"day","week":"week","month":"month"}

def fetch_url(url, encoding="utf-8", timeout=15, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            resp = urllib.request.urlopen(req, timeout=timeout)
            return resp.read().decode(encoding)
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                import threading; threading.Event().wait(0.5 * (attempt + 1))
    raise last_err

def get_realtime(codes):
    if isinstance(codes, str): codes = [codes]
    url = f"https://hq.sinajs.cn/list={','.join(codes)}"
    data = fetch_url(url, encoding="gbk")
    results = []
    for line in data.strip().split("\n"):
        if not line.strip() or '="' not in line: continue
        code = line.split("=")[0].split("_")[-1].strip('"')
        vals = line.split('="')[1].rstrip('";').split(",")
        if len(vals) < 32: continue
        prev = float(vals[2]) if vals[2] else 0
        cur = float(vals[3]) if vals[3] else 0
        chg = cur - prev
        results.append({
            "code":code,"name":vals[0],"current":cur,"open":float(vals[1]) if vals[1] else 0,
            "prev_close":prev,"high":float(vals[4]) if vals[4] else 0,
            "low":float(vals[5]) if vals[5] else 0,"change":round(chg,3),
            "change_pct":round(chg/prev*100,2) if prev else 0,
            "volume":int(vals[8]) if vals[8] else 0,
            "amount":round(float(vals[9])/1e8,2) if vals[9] else 0,
            "date":vals[30] if len(vals)>30 else "","time":vals[31] if len(vals)>31 else "",
        })
    return results

def get_kline(code, days=120, period="day"):
    pt = KLINE_TYPE.get(period, "day")
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},{pt},,,{days},qfq"
    data = json.loads(fetch_url(url))
    inner = data.get("data",{}).get(code,{})
    klines = inner.get(pt,[]) or inner.get(f"qfq{pt}",[]) or inner.get("day",[]) or inner.get("qfqday",[])
    records = []
    for k in klines:
        records.append({"date":k[0],"open":float(k[1]),"close":float(k[2]),
                        "high":float(k[3]),"low":float(k[4]),
                        "volume":int(float(k[5])) if len(k)>5 else 0})
    return records

def search_stock(keyword):
    url = (f"https://searchadapter.eastmoney.com/api/suggest/get?"
           f"input={urllib.request.quote(keyword)}&type=14&count=10")
    data = json.loads(fetch_url(url))
    items = data.get("QuotationCodeTable",{}).get("Data",[]) or []
    results = []
    for it in items:
        code_raw = it.get("Code",""); mkt = it.get("MktNum","")
        if mkt == "1": code = f"sh{code_raw}"
        elif mkt == "0": code = f"sz{code_raw}"
        else: code = code_raw
        results.append({"code":code,"name":it.get("Name",""),"type":it.get("SecurityTypeName","")})
    return results

@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"; response.headers["Expires"] = "0"
    return response

@app.route("/")
def index(): return render_template("index.html")

@app.route("/api/search")
def api_search():
    q = request.args.get("q","")
    if not q: return jsonify([])
    try: return jsonify(search_stock(q))
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/quote/<code>")
def api_quote(code):
    try:
        data = get_realtime(code)
        return jsonify(data[0] if data else {})
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/watchlist", methods=["GET"])
def api_watchlist_get():
    wl = load_watchlist()
    if not wl: return jsonify([])
    quotes = get_realtime([w["code"] for w in wl])
    quote_map = {q["code"]:q for q in quotes}
    for w in wl:
        q = quote_map.get(w["code"],{})
        w.update({k:q.get(k) for k in ("current","change","change_pct","name") if k in q})
    return jsonify(wl)

@app.route("/api/watchlist", methods=["POST"])
def api_watchlist_add():
    item = request.json; wl = load_watchlist()
    if not any(w["code"]==item["code"] for w in wl):
        wl.append({"code":item["code"],"name":item["name"]}); save_watchlist(wl)
    return jsonify({"ok":True})

@app.route("/api/watchlist/<code>", methods=["DELETE"])
def api_watchlist_del(code):
    wl = [w for w in load_watchlist() if w["code"]!=code]; save_watchlist(wl)
    return jsonify({"ok":True})

_WL_ANALYSIS_CACHE = {}
_WL_CACHE_LOCK = threading.Lock()
_WL_ANALYSIS_TTL = 90  # 秒；K线+信号计算缓存，实时行情不缓存


def _watchlist_analysis_item(code, name):
    """单只自选股的 K 线拉取 + 策略分析（带 90s 缓存），供线程池并发调用。"""
    now = time.time()
    with _WL_CACHE_LOCK:
        hit = _WL_ANALYSIS_CACHE.get(code)
        if hit and now - hit[0] < _WL_ANALYSIS_TTL:
            return dict(hit[1], name=name)
    item = {"code": code, "name": name, "score": None,
            "verdict": "Fetch failed", "regime": "", "signals": []}
    try:
        klines = get_kline(code, 60, "day")
        if klines and len(klines) >= 30:
            r = engine.analyze(klines)
            item["score"] = round(r.get("current_score", 50))
            item["verdict"] = r.get("verdict", "")
            item["regime"] = r.get("regime", "")
            item["signals"] = r.get("signals", [])[:3]
        else:
            item.update({"score": None, "verdict": "Insufficient data",
                         "regime": "", "signals": []})
    except Exception:
        pass
    with _WL_CACHE_LOCK:
        _WL_ANALYSIS_CACHE[code] = (time.time(), item)
        if len(_WL_ANALYSIS_CACHE) > 500:  # 防膨胀
            _WL_ANALYSIS_CACHE.clear()
    return dict(item, name=name)


@app.route("/api/watchlist/analyzed")
def api_watchlist_analyzed():
    wl = load_watchlist()
    if not wl: return jsonify([])
    codes = [w["code"] for w in wl]
    try: quotes = get_realtime(codes)
    except: quotes = []
    quote_map = {q["code"]:q for q in quotes}
    # K线+分析：线程池并发拉取（原为逐只串行，网络慢时13只需20s+）
    with ThreadPoolExecutor(max_workers=8) as pool:
        analyses = list(pool.map(
            lambda w: _watchlist_analysis_item(w["code"], w.get("name", w["code"])), wl))
    results = []
    for item in analyses:  # pool.map 保持 wl 顺序
        q = quote_map.get(item["code"], {})
        item.update({k:q.get(k) for k in ("current","change","change_pct","name") if k in q})
        results.append(item)
    return jsonify(results)


@app.route("/api/analyze/<code>")
def api_analyze(code):
    try:
        days = int(request.args.get("days",120))
        period = request.args.get("period","day")
        target_date = request.args.get("date","").strip()
        fetch_days = days+30 if target_date else days
        klines = get_kline(code,fetch_days,period)
        if not klines: return jsonify({"error":"Unable to fetch K-line data"}),500
        future_klines = []
        if target_date:
            past = [k for k in klines if k["date"]<=target_date]
            future_klines = [k for k in klines if k["date"]>target_date][:10]
            klines = past
            if not klines: return jsonify({"error":"No data before "+target_date}),500
        result = engine.analyze(klines)
        result["period"] = period
        if target_date:
            result["target_date"] = target_date
            result["future_klines"] = future_klines
        else:
            rt = get_realtime(code)
            if rt: result["realtime"] = rt[0]
        return jsonify(result)
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/backtest/<code>")
def api_backtest(code):
    try:
        days = int(request.args.get("days",90))
        end_date = request.args.get("end_date","").strip()
        period = request.args.get("period","day")
        all_klines = get_kline(code,days+80,period)
        if not all_klines: return jsonify({"error":"Unable to fetch K-line data"}),500
        if end_date: all_klines = [k for k in all_klines if k["date"]<=end_date]
        backtest_dates = [k["date"] for k in all_klines[-days:]]
        markers = []; last_signal = None
        for date in backtest_dates:
            sub = [k for k in all_klines if k["date"]<=date]
            if len(sub)<30: continue
            result = engine.analyze(sub)
            score = result.get("current_score",50); sigs = result.get("signals",[])
            rc = result.get("risk_control",{})
            sell_sources = [s["source"] for s in sigs if s["type"]=="sell"]
            tp_triggered = rc.get("take_profit_triggered")
            force_sell = any(x in sell_sources for x in ["momentum","top_div"])
            tp_sell = tp_triggered and score<50
            buy_sources = [s["source"] for s in sigs if s["type"]=="buy"]
            has_breakout = "breakout" in [s.get("text","") for s in sigs]
            has_bottom_div = any("bottom_divergence" in s.get("text","") for s in sigs if s["type"]=="buy")
            if force_sell or tp_sell or score<=40:
                if last_signal!="sell":
                    markers.append({"date":date,"signal":"sell","score":score,"verdict":result.get("verdict","")})
                    last_signal = "sell"
            elif score>=60 or has_breakout or has_bottom_div:
                if last_signal!="buy":
                    markers.append({"date":date,"signal":"buy","score":score,"verdict":result.get("verdict","")})
                    last_signal = "buy"
            if tp_triggered and score>=50:
                markers.append({"date":date,"signal":"warn","score":score,"verdict":"TP reference"})
            if any(s["source"]=="RSI" and "overbought" in s.get("text","") for s in sigs):
                markers.append({"date":date,"signal":"warn","score":score,"verdict":"RSI overbought"})
        window_klines = [k for k in all_klines if k["date"] in set(backtest_dates)]
        return jsonify({"klines":window_klines,"markers":markers,"days":days})
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/popular")
def api_popular(): return jsonify(POPULAR)

@app.route("/api/market/indices")
def api_market_indices():
    try:
        quotes = get_realtime(INDEX_CODES); result = []
        for q in quotes:
            q["name"] = INDEX_NAMES.get(q["code"],q["name"])
            try:
                klines = get_kline(q["code"],30,"day")
                q["sparkline"] = [{"date":k["date"],"close":k["close"]} for k in klines]
            except: q["sparkline"] = []
            result.append(q)
        return jsonify(result)
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/market/sectors")
def api_market_sectors():
    sector_type = request.args.get("type","industry")
    fs_param = "m:90+t:2" if sector_type=="industry" else "m:90+t:3"
    fields = "f2,f3,f4,f12,f14,f62,f104,f105,f128,f124"
    url = ("https://push2.eastmoney.com/api/qt/clist/get?"
           "pn=1&pz=200&po=1&np=1&fltt=2&invt=2"
           "&ut=b2884a393a59ad64002292a3e90d46a5"
           f"&fid=f3&fs={fs_param}&fields={fields}")
    try:
        data = json.loads(fetch_url(url))
        diffs = data.get("data",{}).get("diff",[])
        results = []
        for item in diffs:
            results.append({
                "code":str(item.get("f12","")),"name":item.get("f14",""),
                "index":item.get("f2"),"change_pct":item.get("f3"),"change":item.get("f4"),
                "net_inflow":item.get("f62"),"up_count":item.get("f104",0),
                "down_count":item.get("f105",0),
                "leader_code":str(item.get("f128") or ""),"leader_name":item.get("f124",""),
            })
        return jsonify({"total":data.get("data",{}).get("total",0),"sectors":results})
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/market/news")
def api_market_news():
    count = int(request.args.get("count","20"))
    url = f"https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&k=&num={count}&page=1"
    try:
        data = json.loads(fetch_url(url))
        items = data.get("result",{}).get("data",[]) or []
        results = []
        for item in items:
            results.append({
                "id":str(item.get("id","")),"title":item.get("title",""),
                "summary":item.get("intro","") or item.get("summary",""),
                "source":item.get("source","") or item.get("media","") or "Sina Finance",
                "date":item.get("ctime","") or item.get("pubdate",""),"url":item.get("url",""),
                "content":"",
            })
        return jsonify(results)
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/market/news/article")
def api_market_news_article():
    url = request.args.get("url","")
    if not url: return jsonify({"error":"url required"}),400
    try:
        html = fetch_url(url)
        html = re.sub(r'<script[^>]*>.*?</script>','',html,flags=re.DOTALL|re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>','',html,flags=re.DOTALL|re.IGNORECASE)
        paragraphs = re.findall(r'<p[^>]*>(.*?)</p>',html,re.DOTALL)
        text = "\n\n".join(re.sub(r'<[^>]+>','',p).strip()
                          for p in paragraphs if len(re.sub(r'<[^>]+>','',p).strip())>20)
        return jsonify({"content":text[:5000]})
    except Exception as e: return jsonify({"content":"","error":str(e)})

@app.route("/api/minute/<code>")
def api_minute(code):
    try:
        url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?_var=min_data&code={code}"
        raw = fetch_url(url,timeout=10)
        match = re.search(r'min_data\s*=\s*({.*})',raw,re.DOTALL)
        if not match: return jsonify({"error":"Parse failed"}),500
        data = json.loads(match.group(1))
        inner = data.get("data",{}).get(code,{}).get("data",{}).get("data",[])
        if not inner or len(inner)==0: return jsonify({"error":"No minute data"}),500
        items = []
        for line in inner:
            parts = line.split(" ")
            if len(parts)>=2:
                time_str = parts[0]; hh = time_str[:2]; mm = time_str[2:]
                items.append({"time":f"{hh}:{mm}","price":float(parts[1]),
                              "volume":int(parts[2]) if len(parts)>2 else 0,
                              "amount":float(parts[3]) if len(parts)>3 else 0})
        prev_close = None
        try:
            rt = get_realtime(code)
            if rt: prev_close = rt[0].get("prev_close",0)
        except: pass
        return jsonify({"code":code,"prev_close":prev_close,
                       "last_price":items[-1]["price"] if items else 0,"items":items})
    except Exception as e: return jsonify({"error":str(e)}),500

# T+0 Signal API
_t0_signal_cache = {}; _t0_cache_ttl = 60

@app.route("/api/t0-signals/<code>")
def api_t0_signals(code):
    global _t0_signal_cache, _t0_cache_ttl
    import time; now = time.time()
    cached = _t0_signal_cache.get(code)
    if cached and now - cached["ts"] < _t0_cache_ttl: return jsonify(cached["data"])
    try:
        url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?_var=min_data&code={code}"
        raw = fetch_url(url,timeout=10)
        match = re.search(r'min_data\s*=\s*({.*})',raw,re.DOTALL)
        if not match: return jsonify({"error":"Parse failed"}),500
        data = json.loads(match.group(1))
        inner = data.get("data",{}).get(code,{}).get("data",{}).get("data",[])
        if not inner or len(inner)==0: return jsonify({"error":"No minute data"}),500
        items = []
        for line in inner:
            parts = line.split(" ")
            if len(parts)>=2:
                time_str = parts[0]; hh = time_str[:2]; mm = time_str[2:]
                items.append({"time":f"{hh}:{mm}","price":float(parts[1]),
                              "volume":int(parts[2]) if len(parts)>2 else 0,
                              "amount":float(parts[3]) if len(parts)>3 else 0})
        if len(items)<20: return jsonify({"error":"Not enough data","signals":[]}),200
        result = t0_engine.analyze(items); result["code"] = code
        _t0_signal_cache[code] = {"data":result,"ts":now}
        return jsonify(result)
    except Exception as e: return jsonify({"error":str(e),"signals":[]}),500

@app.route("/api/signal-levels/<code>")
def api_signal_levels(code):
    try:
        klines = get_kline(code,120,"day")
        if not klines or len(klines)<30: return jsonify({"error":"K-line data insufficient"}),500
        eng = StockStrategyEngine()
        base_result = eng.analyze(klines)
        base_score = round(base_result.get("current_score",50))
        base_close = klines[-1]["close"]
        buy_level = None; sell_level = None
        ratios = [0.0]
        for r in range(1,810):
            ratios.append(r/1000.0); ratios.append(-r/1000.0)
        for ratio in ratios:
            test_close = round(base_close*(1+ratio),3)
            if test_close<=0: continue
            modified = [dict(k) for k in klines]
            modified[-1]["close"] = test_close
            modified[-1]["high"] = max(modified[-1]["high"],test_close)
            modified[-1]["low"] = min(modified[-1]["low"],test_close)
            result = eng.analyze(modified); score = round(result.get("current_score",50))
            if buy_level is None and score>=60: buy_level = test_close
            if sell_level is None and score<=40: sell_level = test_close
            if buy_level is not None and sell_level is not None: break
        return jsonify({"code":code,"base_close":base_close,"base_score":base_score,
                       "buy_level":buy_level,"sell_level":sell_level,
                       "verdict":base_result.get("verdict",""),
                       "regime":base_result.get("regime","")})
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/sim/account")
def api_sim_account():
    try: return jsonify(sim.get_account())
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/sim/account/reset", methods=["POST"])
def api_sim_reset():
    try:
        capital = request.json.get("capital",100000) if request.json else 100000
        return jsonify(sim.reset_account(int(capital)))
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/sim/cash", methods=["POST"])
def api_sim_cash():
    try:
        amount = float(request.json.get("amount",0))
        return jsonify(sim.update_cash(amount))
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/sim/risk", methods=["POST"])
def api_sim_risk():
    try: return jsonify(sim.update_risk_rules(request.json))
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/sim/capital", methods=["POST"])
def api_sim_capital():
    try:
        amount = float(request.json.get("amount",100000))
        return jsonify(sim.update_capital(amount))
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/sim/order", methods=["POST"])
def api_sim_order():
    try:
        payload = request.json
        result = sim.place_order(code=payload["code"],name=payload["name"],
                                 side=payload["side"],price=float(payload["price"]),
                                 quantity=int(payload["quantity"]),date=payload.get("date"))
        return jsonify(result)
    except Exception as e: return jsonify({"ok":False,"message":str(e)}),400

@app.route("/api/sim/positions")
def api_sim_positions():
    try:
        positions = sim.get_positions()
        if positions:
            codes = [p["code"] for p in positions]
            quotes = get_realtime(codes)
            quote_map = {q["code"]:q for q in quotes}
            sim.refresh_positions(quote_map)
            positions = sim.get_positions()
            for p in positions:
                q = quote_map.get(p["code"],{})
                if q.get("current"):
                    p["current_price"] = q["current"]
                    p["pnl"] = round((q["current"]-p["buy_price"])*p["quantity"],2)
                    p["pnl_pct"] = round((q["current"]-p["buy_price"])/p["buy_price"]*100,2)
                    p["market_value"] = round(q["current"]*p["quantity"],2)
        return jsonify(positions)
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/sim/trades")
def api_sim_trades():
    try:
        limit = int(request.args.get("limit",50))
        return jsonify(sim.get_trades(limit))
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/sim/history")
def api_sim_history():
    try: return jsonify(sim.get_value_history())
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/sim/quote/<code>")
def api_sim_quote(code):
    try:
        data = get_realtime(code)
        if data: return jsonify({"code":code,"name":data[0]["name"],
                                "current":data[0]["current"],"change_pct":data[0]["change_pct"]})
        return jsonify({"error":"No data"}),404
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/api/sim/trades/undo", methods=["POST"])
def api_sim_undo():
    try: return jsonify(sim.undo_last_trade())
    except Exception as e: return jsonify({"ok":False,"message":str(e)}),500

@app.route("/api/sim/positions/<code>", methods=["DELETE"])
def api_sim_delete_position(code):
    try: return jsonify(sim.delete_position(code))
    except Exception as e: return jsonify({"ok":False,"message":str(e)}),500

@app.route("/api/sim/positions/<code>/sell-all", methods=["POST"])
def api_sim_sell_all(code):
    try:
        payload = request.json or {}; price = float(payload.get("price",0))
        if price<=0: return jsonify({"ok":False,"message":"missing price"}),400
        return jsonify(sim.sell_all_position(code,price,payload.get("date")))
    except Exception as e: return jsonify({"ok":False,"message":str(e)}),500

@app.route("/api/sim/autofill", methods=["POST"])
def api_sim_autofill():
    try:
        payload = request.json; start_date = payload.get("start_date","").strip()
        codes = payload.get("codes",[])
        if not start_date or not codes: return jsonify({"error":"missing params"}),400
        end_date = datetime.now().strftime("%Y-%m-%d"); all_bands = []
        for code in codes:
            all_klines = get_kline(code,500,"day")
            if not all_klines or len(all_klines)<60: continue
            buffer_klines = [k for k in all_klines if k["date"]<start_date][-80:]
            window_klines = [k for k in all_klines if start_date<=k["date"]<=end_date]
            full_klines = buffer_klines+window_klines
            if len(full_klines)<30: continue
            backtest_dates = [k["date"] for k in full_klines[-len(window_klines):]]
            markers = []; last_signal = None
            for date in backtest_dates:
                sub = [k for k in full_klines if k["date"]<=date]
                if len(sub)<30: continue
                result = engine.analyze(sub)
                score = result.get("current_score",50); sigs = result.get("signals",[])
                rc = result.get("risk_control",{})
                sell_sources = [s["source"] for s in sigs if s["type"]=="sell"]
                tp_triggered = rc.get("take_profit_triggered")
                force_sell = any(x in sell_sources for x in ["momentum","top_div"])
                tp_sell = tp_triggered and score<50
                buy_sources = [s["source"] for s in sigs if s["type"]=="buy"]
                has_breakout = "breakout" in [s.get("text","") for s in sigs]
                if force_sell or tp_sell or score<=40:
                    if last_signal!="sell":
                        markers.append({"date":date,"signal":"sell","score":score}); last_signal="sell"
                elif score>=60 or has_breakout:
                    if last_signal!="buy":
                        markers.append({"date":date,"signal":"buy","score":score}); last_signal="buy"
            buy_sells = [m for m in markers if m["signal"] in ("buy","sell")]
            bands = []; i = 0
            while i<len(buy_sells)-1:
                a = buy_sells[i]; b = buy_sells[i+1]
                if a["signal"]=="buy" and b["signal"]=="sell":
                    pa = next((k for k in full_klines if k["date"]==a["date"]),None)
                    pb = next((k for k in full_klines if k["date"]==b["date"]),None)
                    if pa and pb:
                        pnl_pct = round((pb["close"]-pa["close"])/pa["close"]*100,2)
                        bands.append({"code":code,"buy_date":a["date"],"buy_price":pa["close"],
                                      "sell_date":b["date"],"sell_price":pb["close"],
                                      "buy_score":a["score"],"sell_score":b["score"],
                                      "profit_pct":pnl_pct,"is_win":pnl_pct>=0})
                    i += 2
                else: i += 1
            all_bands.extend(bands)
        name_map = {}
        for b in all_bands:
            if b["code"] not in name_map:
                try: rt = get_realtime(b["code"]); name_map[b["code"]] = rt[0]["name"] if rt else b["code"]
                except: name_map[b["code"]] = b["code"]
        for b in all_bands: b["name"] = name_map.get(b["code"],b["code"])
        return jsonify({"bands":all_bands,"count":len(all_bands)})
    except Exception as e: return jsonify({"error":str(e)}),500




# ===================== SCREENER =====================
_universe_cache = {"data": None, "ts": 0.0}
_universe_cache_ttl = 300  # 5 minutes


def _fetch_universe_cached():
    """Cached wrapper around _fetch_universe."""
    import time as _t
    now = _t.time()
    if _universe_cache["data"] is not None and now - _universe_cache["ts"] < _universe_cache_ttl:
        return _universe_cache["data"]
    data = _fetch_universe()
    if data:
        _universe_cache["data"] = data
        _universe_cache["ts"] = now
    return data


def _fetch_universe():
    """Fetch A-share stock list from EastMoney with pagination (100/page).

    EastMoney occasionally drops connections - retry each page up to 3 times
    with backoff, and if a page still fails, skip it (partial universe beats
    hard failure, but bail out if the first 3 pages all fail).
    """
    import time as _time
    out = []
    consecutive_failures = 0
    total_seen = 0
    for pn in range(1, 60):
        url = ("https://push2.eastmoney.com/api/qt/clist/get?"
               "pn=" + str(pn) + "&pz=100&po=1&np=1&fltt=2&invt=2"
               "&ut=b2884a393a59ad64002292a3e90d46a5"
               "&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f2,f3,f12,f14")
        data = None
        for attempt in range(3):
            try:
                data = json.loads(fetch_url(url, timeout=10))
                # EastMoney returns JSON null (or {"data": null}) when rate-limiting
                if data is None or not isinstance(data, dict) or not isinstance(data.get("data"), dict):
                    data = None
                    _time.sleep(1.0 * (attempt + 1))
                    continue
                break
            except Exception:
                _time.sleep(0.6 * (attempt + 1))
        if data is None:
            consecutive_failures += 1
            # Skip a flaky page but give up if it keeps failing early
            if consecutive_failures >= 3 and pn <= 5:
                break
            continue
        consecutive_failures = 0
        diff = (data.get("data") or {}).get("diff", [])
        if not diff:
            break
        for it in diff:
            code_raw = str(it.get("f12", ""))
            name = it.get("f14", "")
            price = it.get("f2")
            chg = it.get("f3")
            if not code_raw or price is None or price == "-":
                continue
            prefix = "sh" if code_raw.startswith(("6", "9")) else "sz"
            out.append({"code": prefix + code_raw, "name": name,
                        "price": float(price), "change_pct": float(chg) if chg not in (None, "-") else 0.0})
        total_seen = (data.get("data") or {}).get("total", 0)
        if total_seen and len(out) >= total_seen:
            break
    return out


def _screener_backtest_code(code, days, lookback_days):
    """Run daily backtest for one code, return (win_rate, total_trades, trades, raw_score)."""
    try:
        all_klines = get_kline(code, lookback_days, "day")
        if not all_klines or len(all_klines) < 40:
            return None
        window_dates = [k["date"] for k in all_klines[-days:]]
        markers = []
        last_signal = None
        for date in window_dates:
            sub = [k for k in all_klines if k["date"] <= date]
            if len(sub) < 30:
                continue
            result = engine.analyze(sub)
            score = result.get("current_score", 50)
            sigs = result.get("signals", [])
            rc = result.get("risk_control", {})
            sell_sources = [s["source"] for s in sigs if s["type"] == "sell"]
            tp_triggered = rc.get("take_profit_triggered")
            force_sell = any(x in sell_sources for x in ["momentum", "top_div"])
            tp_sell = tp_triggered and score < 50
            buy_sources = [s["source"] for s in sigs if s["type"] == "buy"]
            has_breakout = "breakout" in [s.get("text", "") for s in sigs]
            has_bottom_div = any("bottom_divergence" in s.get("text", "") for s in sigs if s["type"] == "buy")
            if force_sell or tp_sell or score <= 40:
                if last_signal != "sell":
                    markers.append({"date": date, "signal": "sell", "score": score})
                    last_signal = "sell"
            elif score >= 60 or has_breakout or has_bottom_div:
                if last_signal != "buy":
                    markers.append({"date": date, "signal": "buy", "score": score})
                    last_signal = "buy"
        buy_sells = [m for m in markers if m["signal"] in ("buy", "sell")]
        trades = []
        i = 0
        while i < len(buy_sells) - 1:
            a = buy_sells[i]
            b = buy_sells[i + 1]
            if a["signal"] == "buy" and b["signal"] == "sell":
                pa = next((k for k in all_klines if k["date"] == a["date"]), None)
                pb = next((k for k in all_klines if k["date"] == b["date"]), None)
                if pa and pb:
                    pnl_pct = round((pb["close"] - pa["close"]) / pa["close"] * 100, 2)
                    trades.append({
                        "buy_date": a["date"], "buy_price": pa["close"],
                        "sell_date": b["date"], "sell_price": pb["close"],
                        "profit_pct": pnl_pct, "is_win": pnl_pct >= 0,
                        "buy_score": a["score"], "sell_score": b["score"],
                    })
                i += 2
            else:
                i += 1
        if not trades:
            return None
        wins = [t for t in trades if t["is_win"]]
        win_rate = round(len(wins) / len(trades) * 100, 1)
        avg_profit = round(sum(t["profit_pct"] for t in trades) / len(trades), 2)
        raw_score = round(min(100, win_rate + avg_profit * 3), 1)
        return {"win_rate": win_rate, "total_trades": len(trades),
                "trades": trades, "raw_score": raw_score}
    except Exception:
        return None


def _screener_buy_state(analysis):
    """判定一轮分析结果是否处于「买入状态」，返回 (is_buy, reasons)。

    口径与回测一致：评分≥60 或 当日出现特殊买入信号（放量突破/RSI底背离/
    KDJ低位金叉/MACD金叉）；任一卖出信号或止损触发则整体排除。
    """
    if not analysis or analysis.get("error"):
        return False, []
    score = analysis.get("current_score", 50)
    signals = analysis.get("signals", [])
    risk_control = analysis.get("risk_control", {})

    # 卖出/止损排除（优先级最高）
    has_sell = any(s.get("type") == "sell" for s in signals)
    if risk_control.get("stop_triggered"):
        has_sell = True
    if has_sell:
        return False, []

    is_buy = False
    reasons = []
    # 1. 评分达标 (≥60 建议买入, ≥80 强烈买入)
    if score >= 60:
        is_buy = True
        if score >= 80:
            reasons.append(f"强烈买入信号 (评分{round(score)})")
        else:
            reasons.append(f"建议买入 (评分{round(score)})")
    # 2. 特殊买入信号（即使评分<60）
    for sig in signals:
        if sig.get("type") != "buy":
            continue
        signal_text = sig.get("text", "")
        signal_source = sig.get("source", "")
        if "突破" in signal_text and "放量" in signal_text:
            is_buy = True
            reasons.append("放量突破前高")
        elif "bottom_divergence" in signal_text:
            is_buy = True
            reasons.append("RSI底背离")
        elif "KDJ" in signal_source and "低位金叉" in signal_text:
            is_buy = True
            reasons.append("KDJ低位金叉")
        elif "MACD" in signal_source and "金叉" in signal_text:
            is_buy = True
            reasons.append("MACD金叉")
    return is_buy, reasons


def _market_snapshot_data():
    """Compute market regime from major indices."""
    try:
        quotes = get_realtime(INDEX_CODES)
        if not quotes:
            return None
        total_chg = 0.0
        count = 0
        for q in quotes:
            if q.get("change_pct") is not None:
                total_chg += q["change_pct"]
                count += 1
        avg_chg = total_chg / count if count else 0
        if avg_chg > 0.5:
            regime = "bull"
            min_win_rate = 60
            min_score = 60
            position_limit_pct = 80
            advice = "Market is bullish - higher win-rate threshold, aggressive positions allowed"
        elif avg_chg < -0.5:
            regime = "bear"
            min_win_rate = 75
            min_score = 70
            position_limit_pct = 30
            advice = "Market is weak - be defensive, strict filters, small positions"
        else:
            regime = "neutral"
            min_win_rate = 65
            min_score = 65
            position_limit_pct = 60
            advice = "Market is range-bound - moderate filters, balanced positions"
        vol = sum(abs(q.get("change_pct", 0)) for q in quotes) / count if count else 0
        return {
            "regime": regime,
            "volatility_pct": round(vol, 2),
            "avg_change_pct": round(avg_chg, 2),
            "thresholds": {
                "min_win_rate": min_win_rate,
                "min_score": min_score,
                "position_limit_pct": position_limit_pct,
                "advice": advice,
            },
        }
    except Exception:
        return None


@app.route("/api/screener/market-snapshot")
def api_screener_snapshot():
    try:
        data = _market_snapshot_data()
        if not data:
            return jsonify({"error": "Unable to fetch market data"}), 500
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/screener/run")
def api_screener_run():
    try:
        exchanges = request.args.get("exchange", "sh,sz").split(",")
        boards = request.args.get("board", "main,chinext,star").split(",")
        price_min = float(request.args.get("price_min", 0))
        price_max = float(request.args.get("price_max", 99999))
        min_win_rate = float(request.args.get("min_win_rate", 60))
        min_current_score = float(request.args.get("min_current_score", 60))  # 今日评分阈值
        only_buy_signal = request.args.get("only_buy_signal", "true").lower() == "true"  # 新增：是否只显示买入信号
        days = int(request.args.get("days", 90))
        max_stocks = int(request.args.get("max_stocks", 50))
        sort_by = request.args.get("sort_by", "win_rate")  # 排序方式

        market = _market_snapshot_data()
        if market and market.get("thresholds", {}).get("min_win_rate"):
            effective_min_wr = float(market["thresholds"]["min_win_rate"])
            if min_win_rate <= 0:
                min_win_rate = effective_min_wr

        universe = _fetch_universe_cached()
        if not universe:
            return jsonify({"error": "Unable to fetch stock universe - data source is temporarily unreachable, please retry in a few seconds"}), 502

        total_in_universe = len(universe)
        price_filtered_list = [u for u in universe if price_min <= u["price"] <= price_max]
        price_filtered = len(price_filtered_list)

        lookback_days = days + 80
        results = []
        screened = 0
        score_filtered = 0  # 评分不达标
        no_buy_signal_filtered = 0  # 没有买入信号
        
        for item in price_filtered_list:
            screened += 1
            
            # 获取K线数据并计算当前评分
            try:
                klines = get_kline(item["code"], 120, "day")
                if not klines or len(klines) < 30:
                    continue
                current_analysis = engine.analyze(klines)
                current_score = round(current_analysis.get("current_score", 50))
                current_verdict = current_analysis.get("verdict", "")
                current_regime = current_analysis.get("regime", "")
                current_signals = current_analysis.get("signals", [])
                risk_control = current_analysis.get("risk_control", {})
                # 昨日状态：去掉最后一根K线再分析（边缘触发基准）
                prev_analysis = engine.analyze(klines[:-1]) if len(klines) >= 31 else None
            except:
                continue
            
            # 核心筛选逻辑（边缘触发）：只把「昨日不在买入状态、今日进入买入状态」
            # 的股票视为当天恰好给出买入信号；已成立多日的延续信号不再入选。
            today_buy, buy_reasons = _screener_buy_state(current_analysis)
            if prev_analysis is not None:
                prev_buy, _ = _screener_buy_state(prev_analysis)
            else:
                prev_buy = False
            has_buy_signal = today_buy and not prev_buy

            # 筛选逻辑
            if only_buy_signal and not has_buy_signal:
                no_buy_signal_filtered += 1
                continue
            
            if current_score < min_current_score and not buy_reasons:
                score_filtered += 1
                continue
            
            # 回测计算胜率
            bt = _screener_backtest_code(item["code"], days, lookback_days)
            if not bt:
                continue
            if bt["win_rate"] < min_win_rate:
                continue
                
            # 计算综合评级
            if current_score >= 80 and bt["win_rate"] >= 80:
                final_verdict = "⭐⭐⭐ 强烈推荐"
            elif current_score >= 60 and bt["win_rate"] >= 70:
                final_verdict = "⭐⭐ 推荐买入"
            elif current_score >= 60:
                final_verdict = "⭐ 可以关注"
            else:
                final_verdict = "观望"
            
            freshness_bonus = 5 if len(bt["trades"]) >= 3 else 0
            composite_score = min(100, round(bt["raw_score"] + freshness_bonus, 1))
            
            # 提取前3个买入信号详情
            buy_signals = [s for s in current_signals if s.get("type") == "buy"][:3]
            
            results.append({
                "code": item["code"],
                "name": item["name"],
                "price": item["price"],
                "change_pct": item["change_pct"],
                "current_score": current_score,
                "current_verdict": current_verdict,
                "current_regime": current_regime,
                "buy_reasons": buy_reasons,  # 买入理由列表
                "buy_signals": buy_signals,  # 详细买入信号
                "has_buy_signal": has_buy_signal,
                "signal_age": 0 if has_buy_signal else None,  # 边缘触发：入选即今日新触发
                "stop_loss_price": risk_control.get("stop_loss_price"),  # 止损价
                "win_rate": bt["win_rate"],
                "total_trades": bt["total_trades"],
                "avg_profit": round(sum(t["profit_pct"] for t in bt["trades"]) / len(bt["trades"]), 2) if bt["trades"] else 0,
                "max_profit": max([t["profit_pct"] for t in bt["trades"]], default=0),
                "max_loss": min([t["profit_pct"] for t in bt["trades"]], default=0),
                "trades": bt["trades"][-5:],  # 只返回最近5笔交易
                "composite_score": composite_score,
                "final_verdict": final_verdict,
            })
            
            if len(results) >= max_stocks:
                break

        # 排序：默认按胜率从高到低
        if sort_by == "win_rate":
            results.sort(key=lambda r: (r["win_rate"], r["current_score"]), reverse=True)
        elif sort_by == "current_score":
            results.sort(key=lambda r: (r["current_score"], r["win_rate"]), reverse=True)
        else:
            results.sort(key=lambda r: r["composite_score"], reverse=True)
            
        return jsonify({
            "count": len(results),
            "total_in_universe": total_in_universe,
            "price_filtered": price_filtered,
            "score_filtered": score_filtered,
            "no_buy_signal_filtered": no_buy_signal_filtered,
            "screened": screened,
            "results": results,
            "market": market,
            "filters": {
                "min_win_rate": min_win_rate,
                "min_current_score": min_current_score,
                "only_buy_signal": only_buy_signal,
                "sort_by": sort_by,
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/screener/backtest/<code>")
def api_screener_backtest(code):
    try:
        days = int(request.args.get("days", 90))
        all_klines = get_kline(code, days + 80, "day")
        if not all_klines:
            return jsonify({"error": "Unable to fetch K-line data"}), 500
        backtest_dates = [k["date"] for k in all_klines[-days:]]
        markers = []
        last_signal = None
        for date in backtest_dates:
            sub = [k for k in all_klines if k["date"] <= date]
            if len(sub) < 30:
                continue
            result = engine.analyze(sub)
            score = result.get("current_score", 50)
            sigs = result.get("signals", [])
            rc = result.get("risk_control", {})
            sell_sources = [s["source"] for s in sigs if s["type"] == "sell"]
            tp_triggered = rc.get("take_profit_triggered")
            force_sell = any(x in sell_sources for x in ["momentum", "top_div"])
            tp_sell = tp_triggered and score < 50
            has_breakout = "breakout" in [s.get("text", "") for s in sigs]
            has_bottom_div = any("bottom_divergence" in s.get("text", "") for s in sigs if s["type"] == "buy")
            if force_sell or tp_sell or score <= 40:
                if last_signal != "sell":
                    markers.append({"date": date, "signal": "sell", "score": score})
                    last_signal = "sell"
            elif score >= 60 or has_breakout or has_bottom_div:
                if last_signal != "buy":
                    markers.append({"date": date, "signal": "buy", "score": score})
                    last_signal = "buy"
        window_klines = [k for k in all_klines if k["date"] in set(backtest_dates)]
        return jsonify({"klines": window_klines, "markers": markers, "days": days})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sim/history/daily")
def api_sim_history_daily():
    try:
        history = sim.get_value_history()
        return jsonify(history)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print("\n  * STELLAR A-Share Terminal starting...")
    print("  -> http://localhost:5800\n")
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.run(host="0.0.0.0", port=5800, debug=False, threaded=True)

"""

strategies.py  萦星量化策略引擎 

StockStrategyEngine: 模块化支持自定义权重和严格风控的量化策略类

"""



# ==================== 默认配置 ====================



DEFAULT_CONFIG = {

    # 均线周期

    "ma_periods": [3, 5, 10, 20, 60],    #

    #

    "macd_fast": 8, "macd_slow": 17, "macd_signal": 9,    #

    #

    "rsi_period": 7,    #

    "kdj_n": 9, "kdj_m1": 3, "kdj_m2": 3,

    # ATR 止损

    "atr_period": 14,

    "atr_multiplier": 2.0,

    # 量价

    "volume_surge_ratio": 1.5,

    "volume_lookback": 5,

    #

    "weight_trend": 0.30,        #

    "weight_oscillator": 0.30,   #

    "weight_volume": 0.40,       #

    # 趋势过滤衰减系数

    "regime_decay": 0.5,

    "ma60_slope_window": 5,

    "ma20_slope_window": 3,

    #

    "tp_atr_multiplier": 4.0,

    "tp_rsi_threshold": 80,

    "tp_tiers": [               #

        {"pct": 5, "action": "减仓1/3"},

        {"pct": 10, "action": "再减1/3"},

        {"pct": 15, "action": "清仓"},

    ],

    #

    "hist_slope_bars": 3,        #

    "rsi_divergence_window": 20,    #

    "breakout_lookback": 10,     #

    "vol_div_window": 10,        #

    #

    "strong_buy_threshold": 80,

    "buy_threshold": 60,

    "sell_threshold": 40,

    "strong_sell_threshold": 20,

}





# ==================== 基础指标函数 ====================



def _ma(closes: list, n: int) -> list:

    """ """

    out = []

    for i in range(len(closes)):

        if i < n - 1:

            out.append(None)

        else:

            out.append(round(sum(closes[i - n + 1: i + 1]) / n, 4))

    return out





def _ema(data: list, n: int) -> list:

    """指数移动均线"""

    k = 2 / (n + 1)

    e = [data[0]]

    for v in data[1:]:

        e.append(round(v * k + e[-1] * (1 - k), 4))

    return e





def _macd(closes: list, fast=12, slow=26, sig=9):

    """ """

    dif = [round(a - b, 4) for a, b in zip(_ema(closes, fast), _ema(closes, slow))]

    dea = _ema(dif, sig)

    hist = [round((d - e) * 2, 4) for d, e in zip(dif, dea)]

    return dif, dea, hist





def _rsi(closes: list, n=14) -> list:

    """ """

    out = [None] * n

    gains, losses = [], []

    for i in range(1, len(closes)):

        d = closes[i] - closes[i - 1]

        gains.append(max(d, 0))

        losses.append(max(-d, 0))

    if len(gains) < n:

        return [None] * len(closes)

    ag = sum(gains[:n]) / n

    al = sum(losses[:n]) / n

    out.append(round(100 - 100 / (1 + ag / al), 2) if al else 100)

    for i in range(n, len(gains)):

        ag = (ag * (n - 1) + gains[i]) / n

        al = (al * (n - 1) + losses[i]) / n

        out.append(round(100 - 100 / (1 + ag / al), 2) if al else 100)

    return out





def _kdj(highs: list, lows: list, closes: list, n=9, m1=3, m2=3):

    """ """

    ks, ds, js = [], [], []

    k = d = 50.0

    for i in range(len(closes)):

        s = max(0, i - n + 1)

        hh = max(highs[s: i + 1])

        ll = min(lows[s: i + 1])

        rsv = (closes[i] - ll) / (hh - ll) * 100 if hh != ll else 50

        k = (2 / m1) * rsv + (1 - 2 / m1) * k

        d = (2 / m2) * k + (1 - 2 / m2) * d

        j = 3 * k - 2 * d

        ks.append(round(k, 2)); ds.append(round(d, 2)); js.append(round(j, 2))

    return ks, ds, js





def _atr(highs: list, lows: list, closes: list, n=14) -> list:

    """

    ATR(n)  平均真实波幅

    TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)

    ATR_n = 最近 n 日 TR 的简单平均

    """

    trs = [highs[0] - lows[0]]  # 第一根无前收用振幅代替

    for i in range(1, len(closes)):

        tr = max(

            highs[i] - lows[i],

            abs(highs[i] - closes[i - 1]),

            abs(lows[i] - closes[i - 1]),

        )

        trs.append(round(tr, 4))



    out = [None] * (n - 1)

    for i in range(n - 1, len(trs)):

        out.append(round(sum(trs[i - n + 1: i + 1]) / n, 4))

    return out





# ==================== 策略引擎类 ====================



class StockStrategyEngine:

    """

    量化策略引擎

    用法

        engine = StockStrategyEngine()                    # 默认参数

        engine = StockStrategyEngine({"atr_multiplier": 3.0})  # 自定义参数

        result = engine.analyze(klines)

    """



    def __init__(self, config: dict = None):

        self.cfg = {**DEFAULT_CONFIG, **(config or {})}



    # ==================== Regime Filter ====================



    def _regime(self, closes: list, ma20: list, ma60: list) -> tuple:

        """

        大级别趋势判定返回 (regime, decay, desc)

        多周期共振优化MA60下行时若价格站上MA20且MA20斜率向上

        将decay从0提升至0.5提前释放超跌反弹买入信号

        """

        c = closes[-1]

        m60 = ma60[-1]

        if m60 is None:

            return "bull", 1.0, "MA60 数据不足?默认多头"



        w60 = self.cfg["ma60_slope_window"]

        valid60 = [v for v in ma60[-w60:] if v is not None]

        declining60 = len(valid60) >= 2 and valid60[-1] < valid60[0]



        if c >= m60:

            return "bull", 1.0, f"多头趋势?价格 {c} 在 MA60({m60}) 之上"

        elif declining60:

            #

            w20 = self.cfg["ma20_slope_window"]

            valid20 = [v for v in ma20[-w20:] if v is not None]

            m20 = ma20[-1]

            if m20 and c > m20 and len(valid20) >= 2 and valid20[-1] > valid20[0]:

                return "bear_reversal", 0.5, f"超跌反弹共振?MA20({m20})拐头向上?提前释放买入"

            return "bear", 0.0, f"空头趋势?价格跌破MA60且均线下行"

        else:

            return "weak", self.cfg["regime_decay"], f"弱势震荡?价格在MA60之下但均线走平"



    #



    def _macd_momentum(self, hist: list) -> tuple:

        """

        MACD_hist 动能衰减预警momentum_decay

        判定规则最近连续 N 根 MACD_hist 绝对值递减不论正负

        即 |hist[-3]| > |hist[-2]| > |hist[-1]|输出 momentum_decay 信号

        """

        bars = self.cfg["hist_slope_bars"]  # 默认3

        signals = []

        score = 0



        if len(hist) < bars:

            return score, signals



        recent_abs = [abs(h) for h in hist[-bars:]]



        #

        is_decaying = all(recent_abs[i] < recent_abs[i - 1] for i in range(1, bars))

        if not is_decaying:

            return score, signals



        #

        if hist[-1] > 0:

            #

            score -= 15

            signals.append({"type": "sell", "source": "MACD动能",

                            "text": f"momentum_decay?MACD红柱连续{bars}根缩短?上涨动能衰减"})

        elif hist[-1] < 0:

            #

            score += 15

            signals.append({"type": "buy", "source": "MACD动能",

                            "text": f"momentum_decay?MACD绿柱连续{bars}根缩短?下跌动能衰减"})



        return score, signals



    def _rsi_divergence(self, closes: list, rsi_series: list) -> tuple:

        """

        极简底背离/顶背离检测RSI_bottom_divergence / RSI_top_divergence

        扫描最近 20 根 K 线

        - 底背离当前价格创20日新低但当前RSI 显著高于 20日内RSI最低值  +20分

        - 顶背离当前价格创20日新高但当前RSI 显著低于 20日内RSI最高值  -20分

        """

        win = self.cfg["rsi_divergence_window"]  # 20

        signals = []

        score = 0



        if len(closes) < win or len(rsi_series) < win:

            return score, signals



        price_window = closes[-win:]

        rsi_window = rsi_series[-win:]



        cur_price = price_window[-1]

        cur_rsi = rsi_window[-1]

        if cur_rsi is None:

            return score, signals



        # 过滤None的RSI值

        valid_rsi = [r for r in rsi_window if r is not None]

        if len(valid_rsi) < 5:

            return score, signals



        min_price_20 = min(price_window)

        max_price_20 = max(price_window)

        min_rsi_20 = min(valid_rsi)

        max_rsi_20 = max(valid_rsi)



        #

        if cur_price <= min_price_20 and cur_rsi > min_rsi_20 + 5:

            score += 20

            signals.append({"type": "buy", "source": "RSI背离",

                            "text": f"RSI_bottom_divergence?价格创20日新低但RSI({cur_rsi:.1f})未新低(最低{min_rsi_20:.1f})?底背离确认"})



        #

        if cur_price >= max_price_20 and cur_rsi < max_rsi_20 - 5:

            score -= 20

            signals.append({"type": "sell", "source": "RSI背离",

                            "text": f"RSI_top_divergence?价格创20日新高但RSI({cur_rsi:.1f})未新高(最高{max_rsi_20:.1f})?顶背离确认"})



        return score, signals



    def _breakout_check(self, klines: list) -> tuple:

        """

        放量突破前高今日收盘价 > max(H_{t-10}...H_{t-1}) 且量比>1.5x

        """

        lb = self.cfg["breakout_lookback"]   # 10

        vol_lb = self.cfg["volume_lookback"]  # 5

        signals = []

        score = 0



        if len(klines) < max(lb, vol_lb) + 1:

            return score, signals



        cur = klines[-1]

        #

        recent_highs = [k["high"] for k in klines[-(lb + 1):-1]]

        recent_high = max(recent_highs)

        avg_vol = sum(k["volume"] for k in klines[-(vol_lb + 1):-1]) / vol_lb

        vol_ratio = cur["volume"] / avg_vol if avg_vol > 0 else 0



        if cur["close"] > recent_high and vol_ratio >= self.cfg["volume_surge_ratio"]:

            score += 25  # 强烈信号无视部分均线滞后

            signals.append({"type": "buy", "source": "突破",

                            "text": f"放量突破{lb}日前高{recent_high:.2f}?量比{vol_ratio:.1f}x?"})

        return score, signals



    def _top_divergence_sell(self, klines: list, hist: list) -> tuple:

        """

        高位量价背离卖出 (top_divergence_sell)

        条件当前收盘价处于近20日最高点附近(<2%) + 当日量<前日量 + MACD柱缩短

        触发时强制将综合评分压低至40以下返回score_cap=39

        """

        win = 20

        signals = []

        force_cap = None



        if len(klines) < win or len(hist) < 2:

            return force_cap, signals



        cur = klines[-1]

        prev = klines[-2]

        price_window = [k["close"] for k in klines[-win:]]

        max_price_20 = max(price_window)



        near_top = (max_price_20 - cur["close"]) / max_price_20 < 0.02  # 距极值<2%

        vol_shrink = cur["volume"] < prev["volume"]

        hist_shrink = abs(hist[-1]) < abs(hist[-2])



        if near_top and vol_shrink and hist_shrink:

            force_cap = 39  # 强制压低至40以下

            signals.append({"type": "sell", "source": "高位量缩",

                            "text": f"top_divergence_sell?高位量价背离?当日缩量+MACD柱缩短?建议离场"})



        return force_cap, signals



    #



    def _tiered_take_profit(self, klines: list, atr_val, rsi_val) -> dict:

        """

        阶梯止盈不再要求RSI+ATR并发条件

        返回 TP_Level_1(+5%) / TP_Level_2(+10%) 价格及当前所在档位

        """

        n = self.cfg["atr_period"]

        tiers = self.cfg["tp_tiers"]

        result = {

            "take_profit_triggered": False,

            "take_profit_price": None,

            "tp_distance_pct": None,

            "tp_tier_hit": None,

            "tp_base_price": None,

            "tp_level_1": None,

            "tp_level_2": None,

        }



        if not klines or len(klines) < n:

            return result



        recent = klines[-n:]

        base_price = min(k["close"] for k in recent)

        cur = klines[-1]["close"]

        gain_pct = (cur - base_price) / base_price * 100 if base_price > 0 else 0



        result["tp_base_price"] = base_price

        result["tp_level_1"] = round(base_price * 1.05, 3)

        result["tp_level_2"] = round(base_price * 1.10, 3)



        # ATR止盈价作为参考

        if atr_val:

            tp_price = round(base_price + self.cfg["tp_atr_multiplier"] * atr_val, 3)

            result["take_profit_price"] = tp_price

            result["tp_distance_pct"] = round((tp_price - cur) / cur * 100, 2) if cur else None



        #

        for tier in reversed(tiers):

            if gain_pct >= tier["pct"]:

                result["take_profit_triggered"] = True

                result["tp_tier_hit"] = f"涨幅{gain_pct:.1f}%?建议{tier['action']}"

                break



        # RSI超买共振

        if rsi_val and rsi_val > self.cfg["tp_rsi_threshold"] and gain_pct >= tiers[0]["pct"]:

            result["take_profit_triggered"] = True

            result["tp_tier_hit"] = (result.get("tp_tier_hit") or f"gain:{gain_pct:.1f}%")





        return result



    #



    def _trend_factor(self, closes, ma3, ma5, ma10, ma20, dif, dea, hist,

                       regime: str = "bull") -> tuple:

        """

        趋势因子子分数0~100基准 50

         v2: MA3按Regime条件触发 + 删除MACD动能增强(与金叉共线)

        返回 (score, signals, macd_crossed)

        macd_crossed: 本根K线是否发生了MACD金叉或死叉

        """

        score = 50

        signals = []

        macd_crossed = False  # 追踪本根是否MACD交叉



        #

        if regime != "bull":

            if len(ma3) >= 3 and ma3[-1] and ma3[-2] and ma3[-3]:

                if ma3[-1] > ma3[-2] and ma3[-2] <= ma3[-3]:

                    score += 12

                    signals.append({"type": "buy", "source": "MA3",

                                    "text": "MA3拐头向上?短线动能回升"})

                elif ma3[-1] < ma3[-2] and ma3[-2] >= ma3[-3]:

                    score -= 12

                    signals.append({"type": "sell", "source": "MA3",

                                    "text": "MA3拐头向下?短线动能衰退"})



        # MA 金叉/死叉

        if ma5[-1] and ma10[-1] and ma5[-2] and ma10[-2]:

            if ma5[-1] > ma10[-1] and ma5[-2] <= ma10[-2]:

                score += 20

                signals.append({"type": "buy", "source": "MA", "text": "MA5上穿MA10?金叉?"})

            elif ma5[-1] < ma10[-1] and ma5[-2] >= ma10[-2]:

                score -= 20

                signals.append({"type": "sell", "source": "MA", "text": "MA5下穿MA10?死叉?"})



        # 站上/跌破 MA20

        if ma20[-1] and ma20[-2]:

            if closes[-1] > ma20[-1] and closes[-2] <= ma20[-2]:

                score += 25

                signals.append({"type": "buy", "source": "MA20", "text": "站上20日均线"})

            elif closes[-1] < ma20[-1] and closes[-2] >= ma20[-2]:

                score -= 25

                signals.append({"type": "sell", "source": "MA20", "text": "跌破20日均线"})



        #

        if dif[-1] > dea[-1] and dif[-2] <= dea[-2]:

            bonus = 25 if dif[-1] > 0 else 12

            score += bonus

            signals.append({"type": "buy", "source": "MACD",

                             "text": f"MACD金叉?{'零轴上' if dif[-1]>0 else '零轴下?信号偏弱'}?"})

            macd_crossed = True

        elif dif[-1] < dea[-1] and dif[-2] >= dea[-2]:

            score -= 25

            signals.append({"type": "sell", "source": "MACD", "text": "MACD死叉"})

            macd_crossed = True



        #



        return max(0, min(100, score)), signals, macd_crossed



    #



    def _oscillator_factor(self, rsi_val, k_val, d_val, k_prev, d_prev, decay: float,

                             rsi_divergence_active: bool = False) -> tuple:

        """

        震荡因子子分数0~100基准 50

        decay: Regime Filter 衰减系数0.0~1.0

        rsi_divergence_active: 若已触发RSI背离跳过基础超买超卖判定高级覆盖低级

        返回 (score, signals)

        """

        score = 50

        signals = []



        #

        if rsi_val is not None and not rsi_divergence_active:

            if rsi_val < 20:

                raw = 35

                signals.append({"type": "buy", "source": "RSI", "text": f"RSI={rsi_val} 深度超卖"})

            elif rsi_val < 30:

                raw = 20

                signals.append({"type": "buy", "source": "RSI", "text": f"RSI={rsi_val} 超卖"})

            elif rsi_val > 80:

                raw = -35

                signals.append({"type": "sell", "source": "RSI", "text": f"RSI={rsi_val} 深度超买"})

            elif rsi_val > 70:

                raw = -20

                signals.append({"type": "sell", "source": "RSI", "text": f"RSI={rsi_val} 超买"})

            else:

                raw = 0

            #

            score += raw * decay if raw > 0 else raw



        # KDJ 金叉/死叉

        if k_val is not None and d_val is not None:

            if k_val > d_val and k_prev <= d_prev:

                raw = 30 if k_val < 30 else 15

                label = "低位金叉" if k_val < 30 else "金叉"

                signals.append({"type": "buy", "source": "KDJ", "text": f"KDJ {label}"})

                score += raw * decay  # 买入受衰减

            elif k_val < d_val and k_prev >= d_prev:

                raw = 30 if k_val > 70 else 15

                label = "高位死叉" if k_val > 70 else "死叉"

                signals.append({"type": "sell", "source": "KDJ", "text": f"KDJ {label}"})

                score -= raw  # 卖出不衰减



        return max(0, min(100, score)), signals



    #



    def _volume_factor(self, klines: list) -> tuple:

        """

        量价因子子分数0~100基准 50

         v2: 删除KDJ共振加分KDJ信号严格封锁在震荡因子内保证因子正交性

        返回 (score, signals)

        """

        score = 50

        signals = []

        lb = self.cfg["volume_lookback"]

        ratio = self.cfg["volume_surge_ratio"]



        if len(klines) < lb + 1:

            return score, signals



        avg_vol = sum(k["volume"] for k in klines[-(lb + 1):-1]) / lb

        cur_vol = klines[-1]["volume"]

        cur_close = klines[-1]["close"]

        prev_close = klines[-2]["close"]



        if avg_vol == 0:

            return score, signals



        vol_ratio = cur_vol / avg_vol

        is_up = cur_close > prev_close



        if vol_ratio >= ratio:

            if is_up:

                score += 35

                signals.append({"type": "buy", "source": "VOL",

                                 "text": f"放量上涨?量比{vol_ratio:.1f}x?"})

            else:

                score -= 35

                signals.append({"type": "sell", "source": "VOL",

                                 "text": f"放量下跌?量比{vol_ratio:.1f}x?"})

        elif vol_ratio < 0.7:

            if is_up:

                score -= 10

                signals.append({"type": "warn", "source": "VOL", "text": "缩量上涨?动力不足"})

            else:

                score += 10

                signals.append({"type": "info", "source": "VOL", "text": "缩量下跌?抛压减弱"})

        else:

            if is_up:

                score += 15

                signals.append({"type": "buy", "source": "VOL", "text": "温和放量上涨"})



        return max(0, min(100, score)), signals



    # ==================== 动态止盈模块 ====================

    #

    def _take_profit(self, klines: list, atr_val, rsi_val) -> dict:

        return self._tiered_take_profit(klines, atr_val, rsi_val)



    # ==================== ATR 止损 ====================



    def _risk_control(self, klines: list, atr_series: list) -> dict:

        """

        ATR 动态止损计算

        Stop_Price = P_highest - (k  ATR_14)

        P_highest 取最近 atr_period 根 K 线的最高收盘价

        """

        cfg = self.cfg

        n = cfg["atr_period"]

        k = cfg["atr_multiplier"]

        atr_val = atr_series[-1]

        cur_price = klines[-1]["close"]



        if atr_val is None:

            return {"atr_14": None, "stop_loss_price": None,

                    "stop_triggered": False, "risk_reward_hint": "ATR数据不足"}



        #

        recent = klines[-n:]

        p_highest = max(k_["close"] for k_ in recent)

        stop_price = round(p_highest - k * atr_val, 3)

        stop_triggered = cur_price <= stop_price

        distance = round(cur_price - stop_price, 3)

        distance_pct = round(distance / cur_price * 100, 2) if cur_price else 0



        return {

            "atr_14": round(atr_val, 3),

            "atr_pct": f"{round(atr_val / cur_price * 100, 2)}%",

            "highest_price": p_highest,

            "stop_loss_price": stop_price,

            "trailing_stop_price": stop_price,

            "stop_triggered": stop_triggered,

            "risk_reward_hint": f"止损距离 {distance} ({distance_pct}%)",

        }



    # ==================== 主入口 ====================



    def analyze(self, klines: list) -> dict:

        """

        综合分析入口返回完整策略结果

        klines: [{date, open, high, low, close, volume}, ...]

        """

        if len(klines) < 30:

            return {"error": "数据不足?至少需要30根K线?",

                    "current_score": 50, "verdict": "数据不足"}



        cfg = self.cfg

        closes = [k["close"] for k in klines]

        highs  = [k["high"]  for k in klines]

        lows   = [k["low"]   for k in klines]



        #

        ma3  = _ma(closes, 3)     #

        ma5  = _ma(closes, 5)

        ma10 = _ma(closes, 10)

        ma20 = _ma(closes, 20)

        ma60 = _ma(closes, 60)

        dif, dea, hist = _macd(closes, cfg["macd_fast"], cfg["macd_slow"], cfg["macd_signal"])

        rsi14 = _rsi(closes, cfg["rsi_period"])

        k_vals, d_vals, j_vals = _kdj(highs, lows, closes,

                                      cfg["kdj_n"], cfg["kdj_m1"], cfg["kdj_m2"])

        atr_series = _atr(highs, lows, closes, cfg["atr_period"])



        #

        regime, decay, regime_desc = self._regime(closes, ma20, ma60)



        #

        rsi_div_score, rsi_div_sigs = self._rsi_divergence(closes, rsi14)

        rsi_divergence_active = len(rsi_div_sigs) > 0  # 有背离就跳过基础RSI计分



        #

        t_score, t_sigs, macd_crossed = self._trend_factor(

            closes, ma3, ma5, ma10, ma20, dif, dea, hist, regime)    #

        o_score, o_sigs = self._oscillator_factor(

            rsi14[-1], k_vals[-1], d_vals[-1], k_vals[-2], d_vals[-2], decay,

            rsi_divergence_active)    #

        #

        v_score, v_sigs = self._volume_factor(klines)



        #

        #

        if not macd_crossed:

            macd_mom_score, macd_mom_sigs = self._macd_momentum(hist)

            t_score = max(0, min(100, t_score + macd_mom_score))

            t_sigs.extend(macd_mom_sigs)



        # RSI背离加分到震荡因子

        o_score = max(0, min(100, o_score + rsi_div_score))

        o_sigs.extend(rsi_div_sigs)



        # 放量突破前高

        brk_score, brk_sigs = self._breakout_check(klines)

        v_score = max(0, min(100, v_score + brk_score))

        v_sigs.extend(brk_sigs)



        #

        top_div_cap, top_div_sigs = self._top_divergence_sell(klines, hist)

        v_sigs.extend(top_div_sigs)



        #

        total = round(

            t_score * cfg["weight_trend"] +

            o_score * cfg["weight_oscillator"] +

            v_score * cfg["weight_volume"], 2)



        #

        risk = self._risk_control(klines, atr_series)



        #

        tp = self._take_profit(klines, risk.get("atr_14"), rsi14[-1])

        risk.update(tp)  # 止盈字段合并到 risk_control 返回体中



        #

        if tp["take_profit_triggered"]:

            tier_msg = tp.get("tp_tier_hit", "")

            t_sigs.append({"type": "warn", "source": "止盈",

                           "text": f"阶梯止盈参考?{tier_msg}?建议分批落袋为安"})

        #



        #



        #

        rush_sell_triggered = False

        if len(klines) >= 3:

            cur_close  = klines[-1]["close"]

            prev_close = klines[-2]["close"]   # 前一天收盘

            prev2_close= klines[-3]["close"]   # 前两天收盘

            cur_chg_pct  = (cur_close  - prev_close)  / prev_close  * 100

            prev_chg_pct = (prev_close - prev2_close) / prev2_close * 100

            if prev_chg_pct >= 0:

                #

                if cur_chg_pct <= -5:

                    rush_sell_triggered = True

                    t_sigs.append({"type": "sell", "source": "急跌卷出",

                                   "text": f"当日跌幅{cur_chg_pct:.2f}%?前日涨??超5%卷出线?立即卖出"})

            else:

                #

                combined = prev_chg_pct + cur_chg_pct

                if combined <= -5:

                    rush_sell_triggered = True

                    t_sigs.append({"type": "sell", "source": "急跌卷出",

                                   "text": f"连续两日累计跌幅{combined:.2f}%?天-1:{prev_chg_pct:.2f}% 当日:{cur_chg_pct:.2f}%??超5%卷出线"})



        #

        if rush_sell_triggered:

            total = min(total, 39)

        if top_div_cap is not None:

            total = min(total, top_div_cap)



        #

        if regime == "bear" and total > cfg["strong_buy_threshold"]:

            total = cfg["buy_threshold"] - 1  # 降级为普通买入以下



        #

        if total >= cfg["strong_buy_threshold"]:

            verdict = "强烈买入 "

        elif total >= cfg["buy_threshold"]:

            verdict = "建议买入 "

        elif total <= cfg["strong_sell_threshold"]:

            verdict = "强烈卖出 "

        elif total <= cfg["sell_threshold"]:

            verdict = "建议卖出 "

        else:

            verdict = "观望 "



        #



        all_signals = t_sigs + o_sigs + v_sigs



        return {

            # 核心评分

            "current_score": total,

            "verdict": verdict,

            # 趋势状态

            "regime": regime,

            "regime_desc": regime_desc,

            # 因子明细

            "factors": {

                "trend":      {"score": t_score, "weight": cfg["weight_trend"],

                               "weighted": round(t_score * cfg["weight_trend"], 2),

                               "signals": t_sigs},

                "oscillator": {"score": o_score, "weight": cfg["weight_oscillator"],

                               "weighted": round(o_score * cfg["weight_oscillator"], 2),

                               "signals": o_sigs},

                "volume":     {"score": v_score, "weight": cfg["weight_volume"],

                               "weighted": round(v_score * cfg["weight_volume"], 2),

                               "signals": v_sigs},

            },

            # 风控

            "risk_control": risk,

            # 兼容前端字段

            "score": total,  # 旧字段保留

            "signals": all_signals,

            "indicators": {

                "price": closes[-1],

                "ma3": ma3[-1], "ma5": ma5[-1], "ma10": ma10[-1],

                "ma20": ma20[-1], "ma60": ma60[-1],

                "dif": dif[-1], "dea": dea[-1], "macd": hist[-1],

                "rsi": rsi14[-1],

                "k": k_vals[-1], "d": d_vals[-1], "j": j_vals[-1],

                "atr": risk["atr_14"],

            },

            "klines": [{"date": k["date"], "open": k["open"], "high": k["high"],

                        "low": k["low"], "close": k["close"], "volume": k["volume"]}

                       for k in klines],

            "ma5_series":  ma5,

            "ma10_series": ma10,

            "ma20_series": ma20,

        }



# ==================== 分时T+0信号引擎 ====================



DEFAULT_T0_CONFIG = {

    "t0_macd_fast": 8, "t0_macd_slow": 21, "t0_macd_signal": 5,

    "t0_rsi_period": 9,

    "t0_ma_short": 5, "t0_ma_long": 15,

    "t0_volume_surge_ratio": 2.5, "t0_volume_lookback": 10,

    "t0_divergence_window": 30,

    "t0_rsi_overbought": 75, "t0_rsi_oversold": 25,

    "t0_signal_cooldown_bars": 6,

    "t0_macd_second_div": True,

    "t0_extreme_pct": 3.5,

    "t0_vwap_deviation": 1.8,

    "t0_strong_signal_score": 70,

    "t0_normal_signal_score": 45,

}



class MinuteT0Engine:

    """"""

    def __init__(self, config=None):

        self.cfg = {**DEFAULT_T0_CONFIG, **(config or {})}



    def analyze(self, minute_data):

        items = minute_data

        if len(items) < 20:

            return {"signals": [], "summary": "分时数据不足"}

        prices = [it["price"] for it in items]

        volumes = [it.get("volume", 0) for it in items]

        amounts = [it.get("amount", 0) for it in items]

        cfg = self.cfg

        dif, dea, hist = self._calc_t0_macd(prices)

        rsi = self._calc_rsi(prices, cfg["t0_rsi_period"])

        ma_short = self._calc_sma(prices, cfg["t0_ma_short"])

        ma_long = self._calc_sma(prices, cfg["t0_ma_long"])

        vwap = self._calc_vwap(prices, volumes, amounts)

        deviation_pct = [(prices[i] - vwap[i]) / vwap[i] * 100 if vwap[i] else 0 for i in range(len(prices))]

        vol_ratio = self._calc_volume_ratio(volumes)



        signals = []

        last_signal_idx = -999

        cooldown = cfg["t0_signal_cooldown_bars"]



        for i in range(15, len(prices) - 1):

            score = 0

            reasons_buy = []

            reasons_sell = []

            cur_p = prices[i]

            prev_p = prices[i-1] if i > 0 else cur_p

            cur_rsi = rsi[i] if rsi[i] is not None else 50

            cur_dif = dif[i]; cur_dea = dea[i]; cur_hist = hist[i]

            cur_ma_s = ma_short[i]; cur_ma_l = ma_long[i]

            cur_dev = deviation_pct[i]

            cur_vol_r = vol_ratio[i] if vol_ratio[i] else 1.0



            #

            if self._detect_macd_bottom_div(prices, hist, i):

                score += 30; reasons_buy.append("MACD底背离?价格新低但绿柱缩短?")

            #

            if self._detect_macd_top_div(prices, hist, i):

                score += 30; reasons_sell.append("MACD顶背离?价格新高但红柱缩短?")

            # B: MACD金叉/死叉

            if i >= 1 and cur_dif > cur_dea and dif[i-1] <= dea[i-1]:

                if cur_dif < 0: score += 20; reasons_buy.append("MACD零轴下金叉?超跌反弹?")

                else: score += 12; reasons_buy.append("MACD金叉")

            elif i >= 1 and cur_dif < cur_dea and dif[i-1] >= dea[i-1]:

                if cur_dif > 0: score += 25; reasons_sell.append("MACD零轴上死叉?高位转弱?")

                else: score += 15; reasons_sell.append("MACD死叉")

            # C: RSI超买超卖

            if cur_rsi <= cfg["t0_rsi_oversold"]:

                score += 20; reasons_buy.append(f"RSI超卖({cur_rsi:.0f})")

                prev_vals = [r for r in rsi[max(0,i-4):i] if r is not None]

                if prev_vals and all(r <= cfg["t0_rsi_oversold"] + 5 for r in prev_vals):

                    score += 10; reasons_buy.append("RSI持续超卖")

            elif cur_rsi >= cfg["t0_rsi_overbought"]:

                score += 20; reasons_sell.append(f"RSI超买({cur_rsi:.0f})")

                prev_vals = [r for r in rsi[max(0,i-4):i] if r is not None]

                if prev_vals and all(r >= cfg["t0_rsi_overbought"] - 5 for r in prev_vals):

                    score += 10; reasons_sell.append("RSI持续超买")

            # D: VWAP偏离

            if cur_dev < -cfg["t0_vwap_deviation"]:

                score += 18; reasons_buy.append(f"低于VWAP{abs(cur_dev):.1f}%")

            elif cur_dev > cfg["t0_vwap_deviation"]:

                score += 18; reasons_sell.append(f"高于VWAP{cur_dev:.1f}%")

            # E: 分时均线金叉/死叉

            if i >= 1 and cur_ma_s and cur_ma_l and ma_short[i-1] and ma_long[i-1]:

                if cur_ma_s > cur_ma_l and ma_short[i-1] <= ma_long[i-1]:

                    score += 15; reasons_buy.append("分时均线金叉")

                elif cur_ma_s < cur_ma_l and ma_short[i-1] >= ma_long[i-1]:

                    score += 15; reasons_sell.append("分时均线死叉")

            # F: 极端涨跌幅

            pct_chg = (cur_p - prices[0]) / prices[0] * 100 if prices[0] else 0

            if pct_chg >= cfg["t0_extreme_pct"]:

                score += 35; reasons_sell.append(f"急涨{pct_chg:.1f}%")

            elif pct_chg <= -cfg["t0_extreme_pct"]:

                score += 35; reasons_buy.append(f"急跌{abs(pct_chg):.1f}%")

            # G: 放量方向确认

            if cur_vol_r >= cfg["t0_volume_surge_ratio"]:

                if cur_p > prev_p:

                    score += 10; reasons_buy.append(f"放量上涨")

                else:

                    score += 15; reasons_sell.append(f"放量下跌")

            # H: 量价背离

            if i >= 10:

                price_up = cur_p > prices[i-5]

                vol_trend = sum(volumes[max(0,i-5):i+1]) / 6

                prev_vol_trend = sum(volumes[max(0,i-11):max(0,i-5)]) / 6

                if price_up and vol_trend < prev_vol_trend * 0.8:

                    score += 15; reasons_sell.append("价涨量缩")

                elif not price_up and vol_trend < prev_vol_trend * 0.8:

                    score += 10; reasons_buy.append("价跌量缩")

            #

            if cfg["t0_macd_second_div"] and self._detect_second_macd_div(prices, hist, i, "bottom"):

                score += 25; reasons_buy.append("MACD二次底背离强烈反弹")

            elif cfg["t0_macd_second_div"] and self._detect_second_macd_div(prices, hist, i, "top"):

                score += 25; reasons_sell.append("MACD二次顶背离强烈回落")



            buy_score = sum(1 for _ in reasons_buy) * 10 + score * (1 if len(reasons_buy) > len(reasons_sell) else 0)

            sell_score = sum(1 for _ in reasons_sell) * 10 + score * (1 if len(reasons_sell) > len(reasons_buy) else 0)

            buy_score = min(100, buy_score + score * 0.5)

            sell_score = min(100, sell_score + score * 0.5)

            final_score = max(buy_score, sell_score)

            is_buy = buy_score >= sell_score



            if final_score >= cfg["t0_normal_signal_score"] and (i - last_signal_idx) >= cooldown:

                level = "strong" if final_score >= cfg["t0_strong_signal_score"] else "normal"

                all_reasons = reasons_buy if is_buy else reasons_sell

                signals.append({

                    "time": items[i]["time"], "price": cur_p,

                    "type": "buy" if is_buy else "sell",

                    "score": round(final_score, 0), "level": level,

                    "reasons": all_reasons[:3],

                    "rsi": round(cur_rsi, 1), "macd_hist": round(cur_hist, 6),

                    "vwap_deviation": round(cur_dev, 2), "volume_ratio": round(cur_vol_r, 2),

                })

                last_signal_idx = i



        signals = self._dedup_signals(signals)

        buy_count = sum(1 for s in signals if s["type"] == "buy")

        sell_count = sum(1 for s in signals if s["type"] == "sell")

        strong_count = sum(1 for s in signals if s.get("level") == "strong")

        last_price = prices[-1] if prices else 0

        first_price = prices[0] if prices else 0

        day_chg_pct = round((last_price - first_price) / first_price * 100, 2) if first_price else 0

        day_high = max(prices) if prices else 0; day_low = min(prices) if prices else 0

        day_high_idx = prices.index(day_high) if prices else -1

        day_low_idx = prices.index(day_low) if prices else -1



        return {

            "signals": signals, "buy_count": buy_count, "sell_count": sell_count,

            "strong_count": strong_count,

            "day_high": round(day_high, 3), "day_low": round(day_low, 3),

            "day_high_time": items[day_high_idx]["time"] if day_high_idx >= 0 else "",

            "day_low_time": items[day_low_idx]["time"] if day_low_idx >= 0 else "",

            "day_change_pct": day_chg_pct,

            "summary": f"波幅{round((day_high-day_low)/day_low*100,2) if day_low else 0}% | 买入信号{buy_count} | 卖出信号{sell_count} | 强信号{strong_count}",

            "last_rsi": round(rsi[-1], 1) if rsi and rsi[-1] is not None else None,

            "last_macd_hist": round(hist[-1], 6) if hist else None,

            "last_vwap_deviation": round(deviation_pct[-1], 2) if deviation_pct else 0,

            "last_volume_ratio": round(vol_ratio[-1], 2) if vol_ratio and vol_ratio[-1] else 1.0,

        }



    def _calc_sma(self, data, n):

        out = []

        for i in range(len(data)):

            if i < n - 1: out.append(None)

            else: out.append(round(sum(data[i-n+1:i+1]) / n, 4))

        return out



    def _calc_t0_macd(self, prices):

        fast, slow, sig = self.cfg["t0_macd_fast"], self.cfg["t0_macd_slow"], self.cfg["t0_macd_signal"]

        ema_f = _ema(prices, fast); ema_s = _ema(prices, slow)

        dif = [round(a - b, 6) for a, b in zip(ema_f, ema_s)]

        dea = _ema(dif, sig)

        hist = [round((d - e) * 2, 6) for d, e in zip(dif, dea)]

        return dif, dea, hist



    def _calc_rsi(self, prices, n):

        out = [None] * n

        gains, losses = [], []

        for i in range(1, len(prices)): d = prices[i] - prices[i-1]; gains.append(max(d,0)); losses.append(max(-d,0))

        if len(gains) < n: return [None] * len(prices)

        ag = sum(gains[:n]) / n; al = sum(losses[:n]) / n

        out.append(round(100 - 100 / (1 + ag/al), 2) if al else 100)

        for i in range(n, len(gains)):

            ag = (ag*(n-1)+gains[i])/n; al = (al*(n-1)+losses[i])/n

            out.append(round(100 - 100/(1+ag/al), 2) if al else 100)

        return out



    def _calc_vwap(self, prices, volumes, amounts):
        vwap = []; cum_tpv = 0; cum_vol = 0
        for i in range(len(prices)):
            if volumes[i] > 0:
                cum_tpv += prices[i] * volumes[i]
                cum_vol += volumes[i]
                vwap.append(round(cum_tpv / cum_vol, 4))
            else:
                vwap.append(round(sum(prices[max(0,i-10):i+1]) / (min(i,10)+1), 4))
        return vwap

    def _calc_volume_ratio(self, volumes):

        n = self.cfg["t0_volume_lookback"]

        ratios = [None] * n

        for i in range(n, len(volumes)):

            avg = sum(volumes[i-n:i]) / n

            ratios.append(round(volumes[i] / avg, 2) if avg > 0 else 1.0)

        return ratios



    def _detect_macd_bottom_div(self, prices, hist, idx):

        win = self.cfg["t0_divergence_window"]

        if idx < win: return False

        seg_p = prices[idx-win:idx+1]; seg_h = hist[idx-win:idx+1]

        cur_p = seg_p[-1]; min_p = min(seg_p)

        if cur_p > min_p * 1.01: return False

        min_idx = seg_p.index(min_p)

        return hist[idx] < 0 and seg_h[min_idx] < hist[idx]



    def _detect_macd_top_div(self, prices, hist, idx):

        win = self.cfg["t0_divergence_window"]

        if idx < win: return False

        seg_p = prices[idx-win:idx+1]; seg_h = hist[idx-win:idx+1]

        cur_p = seg_p[-1]; max_p = max(seg_p)

        if cur_p < max_p * 0.99: return False

        max_idx = seg_p.index(max_p)

        return hist[idx] > 0 and seg_h[max_idx] > hist[idx]



    def _detect_second_macd_div(self, prices, hist, idx, direction):

        win = self.cfg["t0_divergence_window"] * 2

        if idx < win: return False

        seg = prices[idx-win:idx+1]; seg_h = hist[idx-win:idx+1]

        if direction == "bottom":

            lows = []

            for i in range(1, len(seg)-1):

                if seg[i] <= seg[i-1] and seg[i] < seg[i+1]: lows.append((i, seg[i], seg_h[i]))

            if len(lows) >= 2:

                a, b = lows[-2], lows[-1]

                if b[1] <= a[1] and b[2] > a[2]: return True

        else:

            highs = []

            for i in range(1, len(seg)-1):

                if seg[i] >= seg[i-1] and seg[i] > seg[i+1]: highs.append((i, seg[i], seg_h[i]))

            if len(highs) >= 2:

                a, b = highs[-2], highs[-1]

                if b[1] >= a[1] and b[2] < a[2]: return True

        return False



    def _dedup_signals(self, signals):

        if len(signals) <= 1: return signals

        merged = []; group = [signals[0]]

        for i in range(1, len(signals)):

            s = signals[i]

            if s["type"] == group[-1]["type"]:

                try:

                    t1 = int(group[-1]["time"].replace(":", ""))

                    t2 = int(s["time"].replace(":", ""))

                    if t2 - t1 > 15:

                        merged.append(max(group, key=lambda x: x["score"]))

                        group = [s]; continue

                except: pass

                group.append(s)

            else:

                merged.append(max(group, key=lambda x: x["score"]))

                group = [s]

        merged.append(max(group, key=lambda x: x["score"]))

        return merged




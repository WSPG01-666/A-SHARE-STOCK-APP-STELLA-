"""
simulation.py — STELLAR 模拟宇宙交易引擎
Virtual trading account with real-time quotes, position tracking, and trade history.
"""

import json
import os
from datetime import datetime
from typing import Optional

SIM_FILE = os.path.join(os.path.dirname(__file__), "simulation.json")

DEFAULT_ACCOUNT = {
    "initial_capital": 100_000,
    "cash": 100_000,
    "positions": [],       # [{code, name, buy_price, buy_date, quantity, current_price, market_value, pnl, pnl_pct}]
    "trades": [],           # [{id, code, name, buy_date, sell_date, buy_price, sell_price, quantity, profit, profit_pct, hold_days}]
    "value_history": [],    # [{date, cash, market_value, total, pnl_pct}]
    "risk_rules": {
        "global_stop_loss_pct": 15,     # 总亏损超15%禁止开仓
        "single_position_pct": 30,      # 单只股票仓位上限
        "commission_rate": 0.0003,      # 佣金万三
        "stamp_tax": 0.001,             # 印花税千一（仅卖出）
    },
    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
}


class SimulationEngine:
    """虚拟交易账户引擎"""

    def __init__(self):
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(SIM_FILE):
            self._save(DEFAULT_ACCOUNT)

    def _load(self) -> dict:
        with open(SIM_FILE, encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data: dict):
        with open(SIM_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── Account ──

    def get_account(self) -> dict:
        acc = self._load()
        # Compute totals
        total_market_value = sum(p.get("market_value", 0) for p in acc["positions"])
        total_pnl = sum(p.get("pnl", 0) for p in acc["positions"])
        total = acc["cash"] + total_market_value
        pnl_pct = round((total - acc["initial_capital"]) / acc["initial_capital"] * 100, 2)
        return {
            "initial_capital": acc["initial_capital"],
            "cash": acc["cash"],
            "market_value": round(total_market_value, 2),
            "total_value": round(total, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": pnl_pct,
            "risk_rules": acc["risk_rules"],
            "created_at": acc.get("created_at", ""),
        }

    def reset_account(self, initial_capital: int = 100_000):
        acc = {**DEFAULT_ACCOUNT, "initial_capital": initial_capital, "cash": initial_capital}
        self._save(acc)
        return self.get_account()

    def update_cash(self, amount: float):
        """Manually set cash balance"""
        acc = self._load()
        acc["cash"] = round(amount, 2)
        self._save(acc)
        return self.get_account()

    def update_capital(self, amount: float):
        """Manually set initial capital (recalculates PnL baseline)"""
        acc = self._load()
        acc["initial_capital"] = round(amount, 2)
        self._save(acc)
        return self.get_account()

    def update_risk_rules(self, rules: dict):
        acc = self._load()
        acc["risk_rules"].update(rules)
        self._save(acc)
        return acc["risk_rules"]

    # ── Positions (update market prices) ──

    def refresh_positions(self, quotes: dict):
        """
        Update position market values from real-time quotes.
        quotes: {code: {current, name}}
        """
        acc = self._load()
        for pos in acc["positions"]:
            q = quotes.get(pos["code"], {})
            if q.get("current"):
                pos["current_price"] = q["current"]
                pos["market_value"] = round(pos["current_price"] * pos["quantity"], 2)
                pos["pnl"] = round((pos["current_price"] - pos["buy_price"]) * pos["quantity"], 2)
                pos["pnl_pct"] = round((pos["current_price"] - pos["buy_price"]) / pos["buy_price"] * 100, 2)
            if q.get("name"):
                pos["name"] = q["name"]
        self._save(acc)
        return acc["positions"]

    def undo_last_trade(self) -> dict:
        """撤回最近一笔交易，恢复现金和持仓"""
        acc = self._load()
        if not acc["trades"]:
            return {"ok": False, "message": "没有可撤回的交易"}
        trade = acc["trades"].pop(0)

        rules = acc["risk_rules"]
        qty = trade.get("quantity", 0)
        buy_price = trade.get("buy_price", 0)
        sell_price = trade.get("sell_price", 0)

        # Reverse the SELL cash flow: we received (revenue - commission - stamp_tax)
        # So we need to subtract that amount from cash
        revenue = sell_price * qty
        sell_commission = revenue * rules["commission_rate"]
        sell_stamp = revenue * rules["stamp_tax"]
        cash_received = revenue - sell_commission - sell_stamp

        # Also reverse the BUY cash flow: we paid (cost + commission)
        # So we need to add that amount back to cash
        cost = buy_price * qty
        buy_commission = cost * rules["commission_rate"]
        cash_paid = cost + buy_commission

        # Net: undo both buy and sell → add back buy cost+fees, remove sell proceeds
        acc["cash"] = round(acc["cash"] + cash_paid - cash_received, 2)

        # Restore the position: merge back the sold shares
        existing_pos = next((p for p in acc["positions"] if p["code"] == trade["code"]), None)
        if existing_pos:
            # Merge: recalculate average buy price
            total_shares = existing_pos["quantity"] + qty
            existing_pos["buy_price"] = round(
                (existing_pos["buy_price"] * existing_pos["quantity"] + buy_price * qty)
                / total_shares, 2)
            existing_pos["quantity"] = total_shares
            existing_pos["market_value"] = round(existing_pos["buy_price"] * total_shares, 2)
        else:
            # Re-create the position
            acc["positions"].append({
                "code": trade["code"],
                "name": trade.get("name", ""),
                "buy_price": buy_price,
                "buy_date": trade.get("buy_date", ""),
                "quantity": qty,
                "current_price": buy_price,
                "market_value": cost,
                "pnl": 0,
                "pnl_pct": 0,
            })

        # Remove the last value snapshot added by this trade
        if acc["value_history"] and len(acc["value_history"]) >= 2:
            acc["value_history"].pop()

        self._save(acc)
        return {"ok": True,
                "message": f"已撤回 {trade.get('name','')} {trade.get('buy_date','')}→{trade.get('sell_date','')}",
                "trade": trade}

    # ── Order ──

    def place_order(self, code: str, name: str, side: str, price: float,
                    quantity: int, date: str = None) -> dict:
        """
        Place a buy or sell order.
        side: "buy" | "sell"
        date: optional historical date string (for backfill)
        Returns {ok, message, account}
        """
        if side not in ("buy", "sell"):
            return {"ok": False, "message": "无效的订单方向"}

        if quantity <= 0:
            return {"ok": False, "message": "数量必须大于0"}

        acc = self._load()
        trade_date = date or datetime.now().strftime("%Y-%m-%d")

        if side == "buy":
            return self._execute_buy(acc, code, name, price, quantity, trade_date)
        else:
            return self._execute_sell(acc, code, name, price, quantity, trade_date)

    def _execute_buy(self, acc: dict, code: str, name: str, price: float,
                     quantity: int, date: str) -> dict:
        rules = acc["risk_rules"]
        total_cost = price * quantity
        commission = total_cost * rules["commission_rate"]
        cash_needed = total_cost + commission

        if acc["cash"] < cash_needed:
            return {"ok": False,
                    "message": f"现金不足！需要 ¥{cash_needed:,.2f}，可用 ¥{acc['cash']:,.2f}"}

        # Check global stop loss
        if acc["initial_capital"] > 0:
            total_loss = acc["initial_capital"] - self._calc_total(acc)
            if total_loss / acc["initial_capital"] * 100 >= rules["global_stop_loss_pct"]:
                return {"ok": False,
                        "message": f"总亏损已达风控线 {rules['global_stop_loss_pct']}%，禁止开仓"}

        # Check single position limit
        max_per_stock = acc["initial_capital"] * rules["single_position_pct"] / 100
        existing = sum(p["market_value"] for p in acc["positions"] if p["code"] == code)
        if existing + total_cost > max_per_stock:
            return {"ok": False,
                    "message": f"单只股票仓位超限（上限 ¥{max_per_stock:,.0f}）"}

        # Deduct cash
        acc["cash"] = round(acc["cash"] - cash_needed, 2)

        # Add or merge position
        existing_pos = next((p for p in acc["positions"] if p["code"] == code), None)
        if existing_pos:
            existing_pos["buy_price"] = round(
                (existing_pos["buy_price"] * existing_pos["quantity"] + total_cost)
                / (existing_pos["quantity"] + quantity), 2)
            existing_pos["quantity"] += quantity
            existing_pos["market_value"] = round(existing_pos["buy_price"] * existing_pos["quantity"], 2)
        else:
            acc["positions"].append({
                "code": code,
                "name": name,
                "buy_price": price,
                "buy_date": date,
                "quantity": quantity,
                "current_price": price,
                "market_value": total_cost,
                "pnl": 0,
                "pnl_pct": 0,
            })

        # Snapshot
        self._snapshot(acc, date)
        self._save(acc)
        return {"ok": True,
                "message": f"✅ 买入 {name} {quantity}股 × ¥{price:.2f}，成交 ¥{total_cost:,.2f}"}

    def _execute_sell(self, acc: dict, code: str, name: str, price: float,
                      quantity: int, date: str) -> dict:
        rules = acc["risk_rules"]
        pos = next((p for p in acc["positions"] if p["code"] == code), None)
        if not pos:
            return {"ok": False, "message": f"不持有 {name}，无法卖出"}
        if pos["quantity"] < quantity:
            return {"ok": False, "message": f"持仓不足（持有 {pos['quantity']} 股）"}

        total_revenue = price * quantity
        commission = total_revenue * rules["commission_rate"]
        stamp_tax = total_revenue * rules["stamp_tax"]
        cash_received = total_revenue - commission - stamp_tax

        # Calculate profit for this trade
        avg_cost = pos["buy_price"] * quantity
        profit = round(total_revenue - avg_cost - commission - stamp_tax, 2)
        profit_pct = round(profit / avg_cost * 100, 2) if avg_cost > 0 else 0

        # Update position
        pos["quantity"] -= quantity
        if pos["quantity"] <= 0:
            acc["positions"] = [p for p in acc["positions"] if p["code"] != code]
        else:
            pos["market_value"] = round(pos["buy_price"] * pos["quantity"], 2)

        acc["cash"] = round(acc["cash"] + cash_received, 2)

        # Record trade
        trade_id = len(acc["trades"]) + 1
        hold_days = self._calc_hold_days(pos["buy_date"], date)
        acc["trades"].insert(0, {
            "id": trade_id,
            "code": code,
            "name": name or pos["name"],
            "buy_date": pos["buy_date"],
            "sell_date": date,
            "buy_price": pos["buy_price"],
            "sell_price": price,
            "quantity": quantity,
            "cost": round(avg_cost, 2),
            "revenue": round(total_revenue, 2),
            "profit": profit,
            "profit_pct": profit_pct,
            "hold_days": hold_days,
        })

        self._snapshot(acc, date)
        self._save(acc)
        return {"ok": True,
                "message": f"✅ 卖出 {name} {quantity}股 × ¥{price:.2f}，{'盈利' if profit >= 0 else '亏损'} ¥{abs(profit):,.2f} ({profit_pct:+.2f}%)"}

    # ── Helpers ──

    def _calc_total(self, acc: dict) -> float:
        mv = sum(p.get("market_value", p["buy_price"] * p["quantity"]) for p in acc["positions"])
        return acc["cash"] + mv

    def _snapshot(self, acc: dict, date: str):
        """Record daily value snapshot for profit chart (maintains chronological order)"""
        mv = sum(p.get("market_value", p["buy_price"] * p["quantity"]) for p in acc["positions"])
        total = acc["cash"] + mv
        pnl_pct = round((total - acc["initial_capital"]) / acc["initial_capital"] * 100, 2)
        entry = {
            "date": date, "cash": acc["cash"],
            "market_value": round(mv, 2), "total": round(total, 2),
            "pnl_pct": pnl_pct,
        }
        # Upsert: replace existing entry for the same date, or insert in sorted position
        history = acc["value_history"]
        for i, h in enumerate(history):
            if h["date"] == date:
                history[i] = entry
                return
            elif h["date"] > date:
                history.insert(i, entry)
                return
        history.append(entry)

    def _calc_hold_days(self, buy_date: str, sell_date: str) -> int:
        try:
            d1 = datetime.strptime(buy_date, "%Y-%m-%d")
            d2 = datetime.strptime(sell_date, "%Y-%m-%d")
            return max(1, (d2 - d1).days)
        except Exception:
            return 1

    # ── Get positions (with optional live quote refresh) ──

    def delete_position(self, code: str) -> dict:
        """直接删除持仓，退还买入成本（含佣金）"""
        acc = self._load()
        pos = next((p for p in acc["positions"] if p["code"] == code), None)
        if not pos:
            return {"ok": False, "message": f"不持有该股票"}
        rules = acc["risk_rules"]
        qty = pos["quantity"]
        buy_cost = pos["buy_price"] * qty
        buy_commission = buy_cost * rules["commission_rate"]
        cash_refund = round(buy_cost + buy_commission, 2)
        acc["cash"] = round(acc["cash"] + cash_refund, 2)
        name = pos.get("name", code)
        acc["positions"] = [p for p in acc["positions"] if p["code"] != code]
        self._save(acc)
        return {"ok": True,
                "message": f"已删除 {name} 持仓（{qty}股），退还 ¥{cash_refund:,.2f}"}

    def sell_all_position(self, code: str, price: float, date: str = None) -> dict:
        """一键清仓：卖出某只股票的全部持仓"""
        acc = self._load()
        pos = next((p for p in acc["positions"] if p["code"] == code), None)
        if not pos:
            return {"ok": False, "message": f"不持有该股票"}
        qty = pos["quantity"]
        name = pos.get("name", code)
        trade_date = date or datetime.now().strftime("%Y-%m-%d")
        return self._execute_sell(acc, code, name, price, qty, trade_date)

    def get_positions(self) -> list:
        return self._load()["positions"]

    def get_trades(self, limit: int = 50) -> list:
        trades = self._load()["trades"]
        return trades[:limit]

    def get_value_history(self) -> list:
        history = self._load()["value_history"]
        # Ensure chronological order (defense-in-depth: _snapshot also maintains order)
        history.sort(key=lambda h: h["date"])
        return history

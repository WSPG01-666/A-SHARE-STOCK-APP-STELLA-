#!/usr/bin/env python3
"""
选股器功能测试脚本
测试"只显示今日可买入的股票，按胜率排序"功能
"""

import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:5800"

def test_screener():
    print("\n" + "="*60)
    print("📊 萦星选股器测试 - 今日买入信号筛选")
    print("="*60 + "\n")
    
    # 测试参数
    params = {
        "min_win_rate": 60,           # 最低胜率60%
        "min_current_score": 60,      # 今日评分≥60
        "only_buy_signal": "true",    # 只显示有买入信号的
        "sort_by": "win_rate",        # 按胜率排序
        "max_stocks": 10,             # 最多返回10只
        "price_min": 5,               # 价格≥5元
        "price_max": 100,             # 价格≤100元
    }
    
    print("🔍 筛选条件：")
    print(f"   - 最低胜率: {params['min_win_rate']}%")
    print(f"   - 今日评分: ≥{params['min_current_score']}分")
    print(f"   - 只显示买入信号: {'是' if params['only_buy_signal'] == 'true' else '否'}")
    print(f"   - 排序方式: 按{'胜率' if params['sort_by'] == 'win_rate' else '评分'}从高到低")
    print(f"   - 价格区间: {params['price_min']}元 ~ {params['price_max']}元")
    print(f"   - 返回数量: 最多{params['max_stocks']}只\n")
    
    print("⏳ 正在扫描全市场股票...\n")
    
    try:
        response = requests.get(f"{BASE_URL}/api/screener/run", params=params, timeout=300)
        
        if response.status_code != 200:
            print(f"❌ 请求失败: {response.status_code}")
            print(f"   错误信息: {response.text}")
            return
        
        data = response.json()
        
        # 显示统计信息
        print("📈 筛选结果统计：")
        print(f"   - 全市场股票: {data.get('total_in_universe', 0)}只")
        print(f"   - 价格筛选后: {data.get('price_filtered', 0)}只")
        print(f"   - 已扫描: {data.get('screened', 0)}只")
        print(f"   - 评分不达标: {data.get('score_filtered', 0)}只")
        print(f"   - 无今日新触发信号: {data.get('no_buy_signal_filtered', 0)}只")
        print(f"   - ✅ 符合条件: {data.get('count', 0)}只\n")
        
        # 显示市场状态
        market = data.get('market', {})
        if market:
            print("🌍 当前市场状态：")
            regime_names = {"bull": "牛市", "bear": "熊市", "neutral": "震荡"}
            print(f"   - 市场状态: {regime_names.get(market.get('regime'), '未知')}")
            print(f"   - 平均涨跌: {market.get('avg_change_pct', 0):+.2f}%")
            print(f"   - 波动率: {market.get('volatility_pct', 0):.2f}%")
            thresholds = market.get('thresholds', {})
            if thresholds:
                print(f"   - 建议胜率阈值: {thresholds.get('min_win_rate', 60)}%")
                print(f"   - 建议仓位上限: {thresholds.get('position_limit_pct', 60)}%")
                print(f"   - 策略建议: {thresholds.get('advice', '')}\n")
        
        # 显示选股结果
        results = data.get('results', [])
        
        if not results:
            print("❌ 未找到符合条件的股票")
            print("💡 建议：")
            print("   1. 降低胜率要求 (如 min_win_rate=50)")
            print("   2. 降低评分要求 (如 min_current_score=50)")
            print("   3. 扩大价格区间")
            return
        
        print(f"\n{'='*80}")
        print(f"🎯 今日买入机会推荐 (共{len(results)}只，按胜率排序)")
        print(f"{'='*80}\n")
        
        for i, stock in enumerate(results, 1):
            print(f"【{i}】 {stock['name']} ({stock['code']})")
            print(f"     💰 现价: ¥{stock['price']:.2f}  今日涨跌: {stock['change_pct']:+.2f}%")
            print(f"     📊 今日评分: {stock['current_score']}分 ({stock['current_verdict']})")
            print(f"     📈 历史胜率: {stock['win_rate']:.1f}% (交易{stock['total_trades']}次)")
            print(f"     💵 平均收益: {stock['avg_profit']:+.2f}%  最大盈利: {stock['max_profit']:+.2f}%")
            
            # 显示买入理由
            if stock.get('buy_reasons'):
                print(f"     🎯 买入理由: {', '.join(stock['buy_reasons'])}")
            
            # 显示止损价
            if stock.get('stop_loss_price'):
                stop_distance = (stock['price'] - stock['stop_loss_price']) / stock['price'] * 100
                print(f"     🛡️ 止损价: ¥{stock['stop_loss_price']:.2f} (距离-{stop_distance:.1f}%)")
            
            # 显示趋势状态
            regime_map = {"bull": "多头🟢", "bear": "空头🔴", "weak": "弱势🟡", "bear_reversal": "反弹共振🟠"}
            regime_label = regime_map.get(stock.get('current_regime', ''), stock.get('current_regime', ''))
            print(f"     🎨 趋势状态: {regime_label}")
            
            # 综合评级
            print(f"     ⭐ 综合评级: {stock['final_verdict']}")
            
            print()
        
        print(f"{'='*80}\n")
        
        # 显示使用建议
        print("💡 使用建议：")
        print("   1. 优先关注胜率≥70%且评分≥70的股票")
        print("   2. 注意止损价，严格执行风控")
        print("   3. 多头趋势的股票成功率更高")
        print("   4. 建议分批买入，控制单只仓位≤30%")
        print("\n✅ 测试完成！\n")
        
    except requests.exceptions.Timeout:
        print("❌ 请求超时（扫描全市场需要较长时间，请稍候重试）")
    except requests.exceptions.ConnectionError:
        print("❌ 连接失败，请确保服务已启动: python app.py")
    except Exception as e:
        print(f"❌ 发生错误: {str(e)}")


if __name__ == "__main__":
    test_screener()

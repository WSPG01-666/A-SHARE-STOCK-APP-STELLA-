# 🎯 选股器使用指南

## 📌 功能说明

选股器已升级为**智能买入信号筛选器**，只显示今日有明确买入信号的股票，按历史胜率从高到低排序。

---

## 🚀 快速开始

### 1. 启动服务
```bash
python app.py
```

### 2. 运行测试脚本
```bash
python test_screener.py
```

### 3. 通过浏览器访问
```
http://localhost:5800/api/screener/run?only_buy_signal=true&sort_by=win_rate
```

---

## 📊 API 参数说明

### 基础参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `only_buy_signal` | boolean | true | 是否只显示有买入信号的股票 |
| `sort_by` | string | win_rate | 排序方式: `win_rate`(胜率) / `current_score`(评分) |
| `min_win_rate` | float | 60 | 最低历史胜率 (%) |
| `min_current_score` | float | 60 | 最低今日评分 |
| `max_stocks` | int | 50 | 最多返回股票数量 |

### 价格筛选

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `price_min` | float | 0 | 最低价格 (元) |
| `price_max` | float | 99999 | 最高价格 (元) |

### 回测参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `days` | int | 90 | 回测天数 |

---

## 🎯 买入信号判定逻辑

> ⚡ **边缘触发（2026-08-28 起）**：选股器只把「**昨日不在买入状态、今日进入买入状态**」的股票视为当天恰好给出买入信号，已成立多日、仅处于延续状态的股票不再出现在结果中。盘中运行时“今日”为实时未收盘 K 线，等价于相对昨日收盘新触发的信号；收盘后运行即为严格的当日新信号。

### 符合以下任一条件即为"有买入信号"：

#### 1️⃣ 评分达标
- ✅ 综合评分 ≥ 60分 → 建议买入
- ✅ 综合评分 ≥ 80分 → 强烈买入

#### 2️⃣ 特殊技术信号（即使评分<60也会显示）
- ✅ 放量突破前高
- ✅ RSI底背离
- ✅ KDJ低位金叉
- ✅ MACD金叉

#### 3️⃣ 排除条件（有以下情况不算买入信号）
- ❌ 有卖出信号（MACD死叉、KDJ死叉等）
- ❌ 触发止损

---

## 📈 使用示例

### 示例 1: 标准选股（推荐）
```bash
# 胜率≥60%, 今日有买入信号, 按胜率排序
curl "http://localhost:5800/api/screener/run?only_buy_signal=true&min_win_rate=60&sort_by=win_rate"
```

### 示例 2: 高胜率选股
```bash
# 胜率≥70%, 评分≥70, 找强势股
curl "http://localhost:5800/api/screener/run?min_win_rate=70&min_current_score=70&sort_by=win_rate"
```

### 示例 3: 激进选股
```bash
# 降低要求, 扩大选股范围
curl "http://localhost:5800/api/screener/run?min_win_rate=50&min_current_score=50&max_stocks=100"
```

### 示例 4: 只看强烈买入
```bash
# 只要评分≥80的强烈买入信号
curl "http://localhost:5800/api/screener/run?min_current_score=80&sort_by=current_score"
```

### 示例 5: 价格筛选
```bash
# 只看10-50元的股票
curl "http://localhost:5800/api/screener/run?price_min=10&price_max=50"
```

---

## 📊 返回数据结构

```json
{
  "count": 10,
  "total_in_universe": 5000,
  "price_filtered": 3500,
  "score_filtered": 200,
  "no_buy_signal_filtered": 800,
  "screened": 150,
  "filters": {
    "min_win_rate": 60,
    "min_current_score": 60,
    "only_buy_signal": true,
    "sort_by": "win_rate"
  },
  "market": {
    "regime": "bull",
    "avg_change_pct": 1.2,
    "volatility_pct": 2.5,
    "thresholds": {
      "min_win_rate": 60,
      "min_score": 60,
      "position_limit_pct": 80,
      "advice": "Market is bullish - higher win-rate threshold, aggressive positions allowed"
    }
  },
  "results": [
    {
      "code": "sh600519",
      "name": "贵州茅台",
      "price": 1680.5,
      "change_pct": 2.3,
      "current_score": 75,
      "current_verdict": "建议买入 🟢",
      "current_regime": "bull",
      "buy_reasons": ["建议买入 (评分75)", "MACD金叉"],
      "buy_signals": [
        {
          "type": "buy",
          "source": "MACD",
          "text": "MACD金叉•零轴上•"
        }
      ],
      "has_buy_signal": true,
      "stop_loss_price": 1620.3,
      "win_rate": 72.5,
      "total_trades": 8,
      "avg_profit": 8.5,
      "max_profit": 15.2,
      "max_loss": -3.5,
      "composite_score": 85.5,
      "final_verdict": "⭐⭐ 推荐买入"
    }
  ]
}
```

---

## 🎨 前端集成示例

### JavaScript 调用示例

```javascript
// 获取今日买入机会
async function getTodayBuyOpportunities() {
    const params = new URLSearchParams({
        only_buy_signal: 'true',
        min_win_rate: 60,
        min_current_score: 60,
        sort_by: 'win_rate',
        max_stocks: 20
    });
    
    const response = await fetch(`/api/screener/run?${params}`);
    const data = await response.json();
    
    // 渲染结果
    renderScreenerResults(data.results);
}

// 渲染结果表格
function renderScreenerResults(results) {
    results.forEach((stock, index) => {
        console.log(`${index + 1}. ${stock.name} (${stock.code})`);
        console.log(`   评分: ${stock.current_score} | 胜率: ${stock.win_rate}%`);
        console.log(`   买入理由: ${stock.buy_reasons.join(', ')}`);
        console.log('---');
    });
}
```

---

## 💡 使用建议

### 🟢 保守策略
```
min_win_rate: 70
min_current_score: 70
只选胜率和评分都很高的股票
```

### 🟡 平衡策略
```
min_win_rate: 60
min_current_score: 60
标准配置，适合大多数情况
```

### 🔴 激进策略
```
min_win_rate: 50
min_current_score: 50
扩大选股范围，但风险较高
```

### 📊 根据市场状态调整

系统会自动判断市场状态（牛市/熊市/震荡），并给出建议阈值：

- **牛市**: 可以适当降低要求，增加仓位
- **熊市**: 提高胜率要求到75%，减少仓位
- **震荡**: 保持标准配置

---

## ⚠️ 注意事项

1. **扫描耗时**: 全市场扫描需要5-10分钟，请耐心等待
2. **数据缓存**: 股票池数据缓存5分钟，K线数据实时获取
3. **风险控制**: 
   - 严格执行止损
   - 单只仓位不超过30%
   - 分批建仓
4. **信号时效**: 信号基于收盘价计算，盘中可能变化
5. **回测局限**: 历史胜率不代表未来收益

---

## 🔧 故障排查

### 问题1: 返回0只股票
**原因**: 筛选条件太严格
**解决**: 
- 降低 `min_win_rate` 到 50
- 降低 `min_current_score` 到 50
- 扩大价格区间

### 问题2: 请求超时
**原因**: 扫描全市场耗时较长
**解决**:
- 增加 `timeout` 参数
- 减少 `max_stocks` 数量
- 缩小价格区间

### 问题3: 数据不准确
**原因**: K线数据获取失败
**解决**:
- 检查网络连接
- 重试几次（数据源偶尔限频）
- 查看控制台错误日志

---

## 📞 技术支持

- 项目地址: F:\projects\stock-app
- 测试脚本: python test_screener.py
- 主程序: python app.py

---

## 🎉 更新日志

### v2.0 (2026-08-20)
- ✅ 新增智能买入信号判定
- ✅ 支持多种技术信号识别
- ✅ 自动排除卖出信号
- ✅ 增加买入理由说明
- ✅ 优化排序逻辑
- ✅ 增加止损价格显示
- ✅ 增加平均收益/最大盈亏统计

### v1.0 (2026-08-17)
- 基础选股功能
- 历史胜率回测

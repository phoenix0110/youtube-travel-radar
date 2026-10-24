---
title: YouTube 旅游选题扫描器
summary: 扫 YouTube 旅游类视频（近 N 天 + 播放量≥阈值），按 B 站人群适配度打分排序，输出选题精选 HTML。
read_when:
  - 用户要找"YouTube 旅游爆款""适合 B 站的旅游二创选题""扫一遍旅游频道最近热门视频"
---

# YouTube Travel Radar

扫描 YouTube 旅游类视频（6 大类型：环球旅行 / 城市探索 / 户外冒险 / 文化体验 / 穷游背包 / 奢华度假），过滤时间窗口+播放量，按 B 站适配度打分出 HTML 选题榜。

## 流程（三步）

```bash
VENV_PY=~/.workbuddy/binaries/python/envs/default/Scripts/python.exe
OUT="C:/Users/yinsh/WorkBuddy/B站二创视频/outputs/research/travel-weekly/<本次目录>"

# 1. 扫描（默认近30天 ≥50万）
"$VENV_PY" ~/.workbuddy/skills/youtube-travel-radar/scripts/scan.py --out "$OUT" [--days 30] [--min-views 500000]

# 2. LLM 打分: 读 <OUT>/videos_raw.json + references/scoring.md
#    → 按 scoring.md 五维打分、标人群(B/E/A/L/K)、写理由+二创标题方向 → <OUT>/scores.json

# 3. 出报告
"$VENV_PY" ~/.workbuddy/skills/youtube-travel-radar/scripts/report.py --dir "$OUT" --title "旅游选题榜" --days 30
```

## 扫描架构（免 API Key，限流安全）

- **频道源**：频道池 RSS（`feeds/videos.xml`，每频道最近 15 条，自带日期+播放量）——不走 yt-dlp 详情，无 bot 限流
- **搜索源**：`ytsearch30:<关键词>` flat 拉取，条目自带 timestamp + view_count，直接过滤
- **频道发现**：搜索命中的爆款频道自动并入频道池再走 RSS 全量拉取，覆盖池外新频道
- 频道池 = `data/channels.txt` + 搜索发现频道
- handle→channel_id 缺的现场解析
- ⚠️ 不要对视频逐条拉 yt-dlp 详情做日期确认——单轮超 ~400 次必触发 YouTube bot 拦截

## 人群体系（评分核心，详见 references/scoring.md）

**B** 背包客/学生（18-28，穷游/间隔年/省钱攻略）| **E** 城市探索（22-35，城市Vlog/美食/建筑）| **A** 户外冒险（20-35，极限运动/徒步/露营）| **L** 奢华精致（28-45，度假/酒店/商务旅行）| **K** 知识/文化（25-40，历史/地理/人文纪录片）

总分 = 0.25×视觉冲击 + 0.20×猎奇新鲜 + 0.15×文化接近 + 0.10×叙事适配 + 0.30×爆点（各维 0-10，详见 scoring.md）

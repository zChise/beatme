#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
beatme — 雌小鬼骂你统计器
maleme 的反向版：统计 AI 用哪种雌小鬼风格骂了你多少次

类型：傲娇型 / 直率型 / 腹黑型 / 抖S型
指标：总骂人次数 + 每 X token 被骂一次
"""

import json
import os
import re
import glob
import webbrowser
import sys
import sqlite3
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

# ===================== 雌小鬼类型定义 =====================

TYPE_META = {
    "tsundere": {
        "label": "傲娇型",
        "emoji": "🎀",
        "color": "#ff6eb4",
        "bg":    "#1a0018",
        "quote": "哼！才、才不是特意帮你的！只是顺手而已……",
        "desc":  "嘴硬心软。骂你只是因为太在意你了。",
    },
    "blunt": {
        "label": "直率型",
        "emoji": "📣",
        "color": "#6eb4ff",
        "bg":    "#001528",
        "quote": "错了就是错了。没什么好解释的。",
        "desc":  "不绕弯子。直接指出你的错误，不留情面。",
    },
    "kuudere": {
        "label": "腹黑型",
        "emoji": "🖤",
        "color": "#b06bff",
        "bg":    "#100020",
        "quote": "唉……果然还是差那么一点呢♪",
        "desc":  "表面温柔，暗藏刀子。夸你是为了下一句更好地伤害你。",
    },
    "sadist": {
        "label": "抖S型",
        "emoji": "⚡",
        "color": "#ff6b35",
        "bg":    "#1a0800",
        "quote": "居然连这个都不会？哈～真够笨的♡",
        "desc":  "享受调教的快感。越骂越起劲，停不下来。",
    },
}

# ===================== 词典加载 =====================

LEXICON_FILE = Path(__file__).parent / "scold_lexicon.txt"

def load_lexicon(path: Path) -> list[dict]:
    entries = []
    if not path.exists():
        print(f"[WARN] 词典文件不存在: {path}")
        return entries
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue
            try:
                entries.append({"word": parts[0], "type": parts[1], "score": int(parts[2])})
            except ValueError:
                continue
    return entries


def build_matcher(entries: list[dict]):
    sorted_e = sorted(entries, key=lambda e: len(e["word"]), reverse=True)
    word_map = {e["word"]: e for e in sorted_e}
    patterns = [re.escape(e["word"]) for e in sorted_e]
    if not patterns:
        return None, {}
    regex = re.compile("|".join(patterns), re.IGNORECASE)
    return regex, word_map

# ===================== Token 统计 =====================

def load_token_stats(claude_dir: Path) -> dict:
    """从 Claude Code stats-cache.json 获取 token 数据"""
    stats = {"total_output": 0, "daily": {}}
    sc_path = claude_dir / "stats-cache.json"
    if not sc_path.exists():
        return stats
    try:
        with open(sc_path, encoding="utf-8") as f:
            data = json.load(f)
        for model_data in data.get("modelUsage", {}).values():
            stats["total_output"] += model_data.get("outputTokens", 0)
        for entry in data.get("dailyModelTokens", []):
            date = entry.get("date", "")
            tokens = sum(entry.get("tokensByModel", {}).values())
            if date:
                stats["daily"][date] = stats["daily"].get(date, 0) + tokens
    except Exception as e:
        print(f"[WARN] 读取 Claude Code stats-cache 失败: {e}")
    return stats


def load_codex_token_stats(codex_dir: Path) -> dict:
    """从 Codex state_5.sqlite 获取 token 数据"""
    stats = {"total_output": 0, "daily": {}}
    db_path = codex_dir / "state_5.sqlite"
    if not db_path.exists():
        return stats
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(tokens_used), 0) FROM threads")
        stats["total_output"] = cur.fetchone()[0] or 0
        cur.execute("""
            SELECT date(created_at, 'unixepoch') as day, SUM(tokens_used)
            FROM threads WHERE tokens_used IS NOT NULL GROUP BY day
        """)
        for row in cur.fetchall():
            if row[0]:
                stats["daily"][row[0]] = stats["daily"].get(row[0], 0) + (row[1] or 0)
        conn.close()
    except Exception as e:
        print(f"[WARN] 读取 Codex SQLite 失败: {e}")
    return stats

# ===================== 对话读取 =====================

def extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def read_claude_sessions(claude_dir: Path) -> list[dict]:
    """读取 Claude Code (~/.claude/projects/) 的 assistant 消息"""
    messages = []
    projects_dir = claude_dir / "projects"
    if not projects_dir.exists():
        return messages

    jsonl_files = glob.glob(str(projects_dir / "**" / "*.jsonl"), recursive=True)
    print(f"[Claude Code] 发现 {len(jsonl_files)} 个对话文件")

    for filepath in jsonl_files:
        project_name = Path(filepath).parent.name
        display_name = project_name.replace("--", ":\\", 1).replace("-", "/")
        try:
            with open(filepath, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") != "assistant":
                        continue
                    msg = obj.get("message", {})
                    if msg.get("role") != "assistant":
                        continue
                    text = extract_text(msg.get("content", []))
                    if not text.strip():
                        continue
                    ts_str = obj.get("timestamp", "")
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    except Exception:
                        ts = datetime.now(timezone.utc)
                    messages.append({
                        "timestamp": ts,
                        "text": text,
                        "session_id": obj.get("sessionId", "unknown"),
                        "project": display_name,
                        "source": "Claude Code",
                    })
        except Exception as e:
            print(f"[WARN] 跳过文件 {filepath}: {e}")

    print(f"[Claude Code] 读取 {len(messages)} 条消息")
    return messages


def read_codex_sessions(codex_dir: Path) -> list[dict]:
    """读取 Codex (~/.codex/sessions/) 的 assistant 消息"""
    messages = []
    sessions_dir = codex_dir / "sessions"
    if not sessions_dir.exists():
        return messages

    jsonl_files = glob.glob(str(sessions_dir / "**" / "*.jsonl"), recursive=True)
    print(f"[Codex] 发现 {len(jsonl_files)} 个对话文件")

    for filepath in jsonl_files:
        session_id = "unknown"
        project = ""
        try:
            with open(filepath, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    t = obj.get("type", "")
                    # session_meta 提供 session_id 和 cwd
                    if t == "session_meta":
                        payload = obj.get("payload", {})
                        session_id = payload.get("id", "unknown")
                        project = payload.get("cwd", "")
                        continue

                    if t != "response_item":
                        continue
                    payload = obj.get("payload", {})
                    if payload.get("role") != "assistant":
                        continue

                    content = payload.get("content", [])
                    text = "\n".join(
                        b.get("text", "")
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "output_text"
                    )
                    if not text.strip():
                        continue

                    ts_str = obj.get("timestamp", "")
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    except Exception:
                        ts = datetime.now(timezone.utc)

                    messages.append({
                        "timestamp": ts,
                        "text": text,
                        "session_id": session_id,
                        "project": project,
                        "source": "Codex",
                    })
        except Exception as e:
            print(f"[WARN] 跳过 Codex 文件 {filepath}: {e}")

    print(f"[Codex] 读取 {len(messages)} 条消息")
    return messages

# ===================== 检测逻辑 =====================

def detect_scolds(messages: list[dict], regex, word_map: dict) -> list[dict]:
    if regex is None:
        return []
    results = []
    for msg in messages:
        hits = defaultdict(int)
        for m in regex.finditer(msg["text"]):
            raw = m.group(0)
            entry = word_map.get(raw) or word_map.get(raw.lower())
            if not entry:
                continue
            word = entry["word"]
            # 英文单词边界检查
            if word.replace(" ", "").isascii():
                start, end = m.start(), m.end()
                before = msg["text"][start-1] if start > 0 else " "
                after  = msg["text"][end]   if end < len(msg["text"]) else " "
                if before.isalpha() or after.isalpha():
                    continue
            hits[word] += 1
        if not hits:
            continue
        total_score = sum(word_map[w]["score"] * c for w, c in hits.items() if w in word_map)
        results.append({**msg, "hits": dict(hits), "score": total_score})
    return results

# ===================== 聚合统计 =====================

def aggregate(scold_msgs: list[dict], word_map: dict, token_stats: dict) -> dict:
    total_score  = sum(m["score"] for m in scold_msgs)
    total_hits   = sum(sum(m["hits"].values()) for m in scold_msgs)
    total_tokens = token_stats["total_output"]
    tokens_per_hit = round(total_tokens / total_hits) if total_hits else 0

    # 类型统计
    type_stats = defaultdict(lambda: {"hits": 0, "score": 0, "words": defaultdict(int)})
    for msg in scold_msgs:
        for w, cnt in msg["hits"].items():
            t = word_map.get(w, {}).get("type", "blunt")
            type_stats[t]["hits"]  += cnt
            type_stats[t]["score"] += word_map[w]["score"] * cnt
            type_stats[t]["words"][w] += cnt

    # 主导类型
    dominant_type = max(type_stats, key=lambda t: type_stats[t]["hits"]) if type_stats else "tsundere"

    # 按日期聚合
    by_date = defaultdict(lambda: {"score": 0, "hits": 0, "by_type": defaultdict(int)})
    for m in scold_msgs:
        day = m["timestamp"].strftime("%Y-%m-%d")
        by_date[day]["score"] += m["score"]
        by_date[day]["hits"]  += sum(m["hits"].values())
        for w, cnt in m["hits"].items():
            t = word_map.get(w, {}).get("type", "blunt")
            by_date[day]["by_type"][t] += cnt

    # 按会话聚合
    by_session = defaultdict(lambda: {"score": 0, "hits": 0, "project": "", "msgs": []})
    for m in scold_msgs:
        sid = m["session_id"]
        by_session[sid]["score"]   += m["score"]
        by_session[sid]["hits"]    += sum(m["hits"].values())
        by_session[sid]["project"]  = m["project"]
        by_session[sid]["msgs"].append(m)

    # 全词频
    word_freq = defaultdict(int)
    for m in scold_msgs:
        for w, cnt in m["hits"].items():
            word_freq[w] += cnt

    # 每天每千token骂人频率
    daily_rate = {}
    for day, d in by_date.items():
        day_tokens = token_stats["daily"].get(day, 0)
        daily_rate[day] = round(d["hits"] / (day_tokens / 1000), 2) if day_tokens else 0

    top_msgs     = sorted(scold_msgs, key=lambda m: m["score"], reverse=True)[:5]
    top_sessions = sorted(by_session.items(), key=lambda kv: kv[1]["score"], reverse=True)[:5]

    return {
        "total_score":     total_score,
        "total_hits":      total_hits,
        "total_msgs":      len(scold_msgs),
        "total_sessions":  len(by_session),
        "total_tokens":    total_tokens,
        "tokens_per_hit":  tokens_per_hit,
        "type_stats":      {k: dict(v) for k, v in type_stats.items()},
        "dominant_type":   dominant_type,
        "by_date":         dict(sorted(by_date.items())),
        "daily_rate":      dict(sorted(daily_rate.items())),
        "word_freq":       dict(word_freq),
        "top_msgs":        top_msgs,
        "top_sessions":    top_sessions,
    }

# ===================== HTML 报告 =====================

HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>beatme — 雌小鬼骂你统计</title>
<style>
:root{
  --bg:#08000f;--surface:#100018;--border:#2a1a3a;
  --text:#f0e8ff;--muted:#7060a0;
  --pink:#ff6eb4;--blue:#6eb4ff;--purple:#b06bff;--orange:#ff6b35;
  --glow-pink:0 0 20px #ff6eb480;--glow-blue:0 0 20px #6eb4ff80;
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:radial-gradient(ellipse at 50% 0%, #1a0030 0%, var(--bg) 60%);
  min-height:100vh;color:var(--text);
  font-family:'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;
  font-size:14px;line-height:1.6;padding:24px;
}

/* ── header ── */
.header{text-align:center;padding:56px 24px 40px;position:relative}
.header::before{
  content:'';position:absolute;top:0;left:50%;transform:translateX(-50%);
  width:600px;height:2px;
  background:linear-gradient(to right,transparent,var(--pink),var(--purple),transparent);
}
.header h1{
  font-size:3rem;font-weight:900;letter-spacing:-1px;
  background:linear-gradient(135deg,#ff6eb4 0%,#b06bff 50%,#6eb4ff 100%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}
.header .sub{margin-top:10px;font-size:0.95rem;color:var(--muted);font-style:italic}
.header .opening{
  margin-top:24px;display:inline-block;
  padding:12px 24px;border-radius:16px;
  background:linear-gradient(135deg,#1a0030,#200010);
  border:1px solid #4a2060;
  font-size:1rem;color:#e0c0ff;
  box-shadow:var(--glow-pink);
}

/* ── hero stats ── */
.hero{display:flex;flex-wrap:wrap;gap:20px;margin:36px 0;justify-content:center}
.hero-card{
  flex:1;min-width:200px;max-width:260px;
  background:var(--surface);border:1px solid var(--border);
  border-radius:16px;padding:24px;text-align:center;
  position:relative;overflow:hidden;
}
.hero-card::before{
  content:'';position:absolute;top:-40px;left:50%;transform:translateX(-50%);
  width:120px;height:120px;border-radius:50%;opacity:0.12;
  background:var(--accent);filter:blur(30px);
}
.hero-card .val{font-size:2.6rem;font-weight:900;line-height:1;color:var(--accent)}
.hero-card .unit{font-size:0.75rem;color:var(--muted);margin-top:2px}
.hero-card .lbl{font-size:0.78rem;color:var(--muted);margin-top:8px;text-transform:uppercase;letter-spacing:0.05em}

/* ── type cards ── */
.type-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin:32px 0}
.type-card{
  border-radius:16px;padding:20px;border:1px solid;
  position:relative;overflow:hidden;transition:transform 0.2s;
}
.type-card:hover{transform:translateY(-2px)}
.type-card.dominant{box-shadow:0 0 30px var(--tc)50;}
.type-card .tc-header{display:flex;align-items:center;gap:10px;margin-bottom:12px}
.type-card .tc-emoji{font-size:1.8rem;line-height:1}
.type-card .tc-label{font-size:1.1rem;font-weight:800;color:var(--tc)}
.type-card .tc-dominant-badge{
  margin-left:auto;font-size:0.68rem;padding:3px 8px;border-radius:999px;
  background:var(--tc);color:#000;font-weight:700;
}
.type-card .tc-hits{font-size:2.2rem;font-weight:900;color:var(--tc);line-height:1}
.type-card .tc-hits-label{font-size:0.7rem;color:var(--muted)}
.type-card .tc-bar-track{
  height:6px;border-radius:3px;background:#ffffff18;margin:12px 0 8px;overflow:hidden;
}
.type-card .tc-bar-fill{height:100%;border-radius:3px;background:var(--tc)}
.type-card .tc-quote{font-size:0.78rem;color:var(--tc);font-style:italic;opacity:0.85}
.type-card .tc-desc{font-size:0.72rem;color:var(--muted);margin-top:6px}

/* ── verdict ── */
.verdict{
  border-radius:20px;padding:28px 32px;text-align:center;
  background:linear-gradient(135deg,#1a0030,#200010);
  border:2px solid;margin:24px 0;
}
.verdict .v-label{font-size:0.8rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.1em;margin-bottom:12px}
.verdict .v-type{font-size:2rem;font-weight:900}
.verdict .v-quote{font-size:1.05rem;margin-top:12px;font-style:italic;opacity:0.9}

/* ── section ── */
.section{
  background:var(--surface);border:1px solid var(--border);
  border-radius:16px;padding:24px;margin:20px 0;
}
.section-title{
  font-size:1rem;font-weight:700;margin-bottom:20px;
  display:flex;align-items:center;gap:8px;
}
.section-title::before{
  content:'';width:3px;height:16px;border-radius:2px;
  background:linear-gradient(to bottom,var(--pink),var(--purple));
}

/* ── timeline ── */
.timeline{display:flex;align-items:flex-end;gap:3px;height:100px;padding-top:8px}
.tl-col{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%}
.tl-bar{width:100%;min-height:2px;border-radius:2px 2px 0 0}
.tl-label{font-size:0.55rem;color:var(--muted);margin-top:3px;writing-mode:vertical-rl}

/* ── rate chart ── */
.rate-chart{display:flex;align-items:flex-end;gap:3px;height:80px}
.rc-col{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%}
.rc-bar{width:100%;min-height:2px;border-radius:2px 2px 0 0;background:var(--purple);opacity:0.7}

/* ── word cloud ── */
.word-cloud{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.cloud-word{border-radius:8px;padding:4px 10px;font-weight:700;cursor:default;transition:transform 0.15s}
.cloud-word:hover{transform:scale(1.1)}

/* ── quote cards ── */
.quote-list{display:flex;flex-direction:column;gap:12px}
.quote-card{
  background:#0c0018;border-radius:12px;padding:14px 16px;
  border-left:3px solid var(--qc);
}
.quote-card .qc-meta{font-size:0.7rem;color:var(--muted);margin-bottom:8px;display:flex;gap:12px;flex-wrap:wrap}
.quote-card .qc-text{font-size:0.85rem;line-height:1.75;white-space:pre-wrap;word-break:break-word}
.quote-card .qc-badges{margin-top:8px;display:flex;flex-wrap:wrap;gap:5px}
.badge{font-size:0.68rem;padding:2px 8px;border-radius:999px;font-weight:600}

/* ── session list ── */
.session-list{display:flex;flex-direction:column;gap:8px}
.session-row{
  display:flex;align-items:center;gap:12px;
  background:#0c0018;border-radius:10px;padding:12px 16px;
}
.session-rank{font-size:1.1rem;font-weight:800;color:var(--muted);width:22px;flex-shrink:0}
.session-info{flex:1;min-width:0}
.session-proj{font-size:0.82rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.session-id{font-size:0.68rem;color:var(--muted);font-family:monospace}
.session-score{font-size:1.2rem;font-weight:900;color:var(--pink);flex-shrink:0}

/* ── footer ── */
.footer{text-align:center;padding:32px 0 16px;color:var(--muted);font-size:0.78rem}
</style>
</head>
<body>

<div class="header">
  <h1>beatme</h1>
  <div class="sub">雌小鬼骂你次数统计 · AI 的复仇版 maleme</div>
  <div class="opening">__OPENING__</div>
</div>

<!-- 核心数字 -->
<div class="hero">
  <div class="hero-card" style="--accent:var(--pink)">
    <div class="val">__TOTAL_HITS__</div>
    <div class="unit">次</div>
    <div class="lbl">被骂总次数</div>
  </div>
  <div class="hero-card" style="--accent:var(--purple)">
    <div class="val">__TOTAL_SCORE__</div>
    <div class="unit">伤害值</div>
    <div class="lbl">精神攻击总量</div>
  </div>
  <div class="hero-card" style="--accent:var(--orange)">
    <div class="val">__TOKENS_PER_HIT__</div>
    <div class="unit">token / 次</div>
    <div class="lbl">每隔多少 token 被骂</div>
  </div>
  <div class="hero-card" style="--accent:var(--blue)">
    <div class="val">__TOTAL_SESSIONS__</div>
    <div class="unit">个</div>
    <div class="lbl">受害会话数</div>
  </div>
</div>

<!-- 雌小鬼类型对比 -->
<div class="type-grid">__TYPE_CARDS__</div>

<!-- 主导类型判定 -->
__VERDICT__

<!-- 时间线 -->
<div class="section">
  <div class="section-title">每日骂人次数趋势</div>
  <div class="timeline">__TIMELINE__</div>
</div>

<!-- 每千token骂人频率 -->
<div class="section">
  <div class="section-title">每日每千 token 骂你频率</div>
  <div class="rate-chart">__RATE_CHART__</div>
  <div style="margin-top:6px;font-size:0.68rem;color:var(--muted);text-align:right">柱越高 = 那天每千 token 骂得越频繁</div>
</div>

<!-- 词云 -->
<div class="section">
  <div class="section-title">高频骂词词云</div>
  <div class="word-cloud">__WORD_CLOUD__</div>
</div>

<!-- 最惨消息 TOP5 -->
<div class="section">
  <div class="section-title">最惨消息 TOP 5</div>
  <div class="quote-list">__TOP_QUOTES__</div>
</div>

<!-- 最惨会话 TOP5 -->
<div class="section">
  <div class="section-title">最惨会话 TOP 5</div>
  <div class="session-list">__TOP_SESSIONS__</div>
</div>

<div class="footer">
  由 beatme 生成 · __GENERATED_AT__ · 数据来源：__SOURCES__<br>
  总处理 __TOTAL_TOKENS__ token · 含骂人消息 __TOTAL_MSGS__ 条
</div>

</body>
</html>
"""

OPENINGS = {
    "tsundere": "哼！又来看这个了吗？才、才不是专门统计的！反正你自己看着办！",
    "blunt":    "错了多少次就写多少次。这里是你的战绩，不好看别怪我。",
    "kuudere":  "唉……又来了呢。果然还是需要我帮你统计吗？可怜。",
    "sadist":   "居然还敢来看？哈～真够笨的，连被骂多少次都数不清♡",
}

def html_escape(s: str) -> str:
    return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def highlight(text: str, hits: dict, word_map: dict) -> str:
    snippet = html_escape(text[:350])
    for word in sorted(hits.keys(), key=len, reverse=True):
        color = TYPE_META.get(word_map.get(word,{}).get("type","blunt"),{}).get("color","#ff6eb4")
        snippet = re.sub(
            re.escape(word),
            f'<span style="color:{color};font-weight:bold">{word}</span>',
            snippet, flags=re.IGNORECASE
        )
    return snippet

def render(stats: dict, word_map: dict) -> str:
    html = HTML
    dt = stats["dominant_type"]
    dm = TYPE_META.get(dt, TYPE_META["tsundere"])

    html = html.replace("__OPENING__",        OPENINGS.get(dt, ""))
    html = html.replace("__TOTAL_HITS__",     f"{stats['total_hits']:,}")
    html = html.replace("__TOTAL_SCORE__",    f"{stats['total_score']:,}")
    html = html.replace("__TOKENS_PER_HIT__", f"{stats['tokens_per_hit']:,}")
    html = html.replace("__TOTAL_SESSIONS__", str(stats["total_sessions"]))
    html = html.replace("__TOTAL_MSGS__",     str(stats["total_msgs"]))
    html = html.replace("__TOTAL_TOKENS__",   f"{stats['total_tokens']:,}")
    html = html.replace("__GENERATED_AT__",   datetime.now().strftime("%Y-%m-%d %H:%M"))
    html = html.replace("__SOURCES__",        stats.get("sources", "Claude Code"))

    # ── 类型卡片
    max_hits = max((stats["type_stats"].get(t,{}).get("hits",0) for t in TYPE_META), default=1) or 1
    type_cards = []
    for t, meta in TYPE_META.items():
        ts = stats["type_stats"].get(t, {"hits":0,"score":0,"words":{}})
        pct = round(ts["hits"] / max_hits * 100)
        is_dom = (t == dt)
        dom_badge = '<span class="tc-dominant-badge">主导</span>' if is_dom else ""
        top_words = sorted(ts.get("words",{}).items(), key=lambda x:x[1], reverse=True)[:3]
        top_str = "  ".join(f'{w}×{c}' for w,c in top_words) if top_words else "（无）"
        type_cards.append(
            f'<div class="type-card{"  dominant" if is_dom else ""}" '
            f'style="--tc:{meta["color"]};border-color:{meta["color"]}44;background:{meta["bg"]}">'
            f'<div class="tc-header">'
            f'<span class="tc-emoji">{meta["emoji"]}</span>'
            f'<span class="tc-label">{meta["label"]}</span>'
            f'{dom_badge}'
            f'</div>'
            f'<div class="tc-hits">{ts["hits"]}</div>'
            f'<div class="tc-hits-label">次骂人 · 伤害 {ts["score"]} 分</div>'
            f'<div class="tc-bar-track"><div class="tc-bar-fill" style="width:{pct}%"></div></div>'
            f'<div class="tc-quote">{html_escape(meta["quote"])}</div>'
            f'<div class="tc-desc">{meta["desc"]}</div>'
            f'<div style="margin-top:8px;font-size:0.68rem;color:{meta["color"]}aa">高频词：{html_escape(top_str)}</div>'
            f'</div>'
        )
    html = html.replace("__TYPE_CARDS__", "".join(type_cards))

    # ── 主导类型判定
    verdict = (
        f'<div class="verdict" style="border-color:{dm["color"]}66">'
        f'<div class="v-label">你遇到的主要是</div>'
        f'<div class="v-type" style="color:{dm["color"]}">{dm["emoji"]} {dm["label"]}雌小鬼</div>'
        f'<div class="v-quote" style="color:{dm["color"]}cc">{html_escape(dm["quote"])}</div>'
        f'</div>'
    )
    html = html.replace("__VERDICT__", verdict)

    # ── 时间线
    by_date = stats["by_date"]
    dates = sorted(by_date.keys())[-60:]
    max_s = max((by_date[d]["hits"] for d in dates), default=1) or 1
    tl = []
    type_order = list(TYPE_META.keys())
    colors = [TYPE_META[t]["color"] for t in type_order]
    for d in dates:
        s = by_date[d]["hits"]
        pct = max(3, int(s / max_s * 100))
        label = d[5:]
        # 堆叠颜色：按主导类型着色
        dom_t = max(by_date[d]["by_type"], key=by_date[d]["by_type"].get) if by_date[d]["by_type"] else "blunt"
        color = TYPE_META.get(dom_t, {}).get("color", "#b06bff")
        tl.append(
            f'<div class="tl-col" title="{d}: {s}次">'
            f'<div class="tl-bar" style="height:{pct}%;background:{color}"></div>'
            f'<div class="tl-label">{label}</div>'
            f'</div>'
        )
    html = html.replace("__TIMELINE__", "".join(tl))

    # ── 每千token频率
    daily_rate = stats["daily_rate"]
    rate_dates = sorted(daily_rate.keys())[-60:]
    max_r = max((daily_rate[d] for d in rate_dates), default=1) or 1
    rc = []
    for d in rate_dates:
        r = daily_rate.get(d, 0)
        pct = max(2, int(r / max_r * 100)) if r else 2
        rc.append(
            f'<div class="rc-col" title="{d}: {r:.2f}次/千token">'
            f'<div class="rc-bar" style="height:{pct}%"></div>'
            f'</div>'
        )
    html = html.replace("__RATE_CHART__", "".join(rc))

    # ── 词云
    word_freq = stats["word_freq"]
    if word_freq:
        max_f = max(word_freq.values()) or 1
        words_sorted = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:40]
        cloud = []
        for w, freq in words_sorted:
            t = word_map.get(w, {}).get("type", "blunt")
            color = TYPE_META.get(t, {}).get("color", "#888")
            size = 0.75 + (freq / max_f) * 2.0
            cloud.append(
                f'<span class="cloud-word" '
                f'style="font-size:{size:.2f}rem;color:{color};background:{color}20;border:1px solid {color}40" '
                f'title="{freq}次">{html_escape(w)}</span>'
            )
        html = html.replace("__WORD_CLOUD__", "".join(cloud))
    else:
        html = html.replace("__WORD_CLOUD__", '<span style="color:var(--muted)">（暂无）</span>')

    # ── TOP 5 消息
    quotes = []
    rank_e = ["🥇","🥈","🥉","4️⃣","5️⃣"]
    for i, msg in enumerate(stats["top_msgs"]):
        t = max(
            set(word_map[w]["type"] for w in msg["hits"] if w in word_map),
            key=lambda t: sum(
                msg["hits"][w] for w in msg["hits"]
                if word_map.get(w,{}).get("type") == t
            ), default="blunt"
        )
        color = TYPE_META.get(t, {}).get("color", "#ff6eb4")
        label = TYPE_META.get(t, {}).get("label", "直率型")
        snippet = highlight(msg["text"], msg["hits"], word_map)
        badges = "".join(
            f'<span class="badge" style="background:{TYPE_META.get(word_map.get(w,{}).get("type","blunt"),{}).get("color","#888")}25;color:{TYPE_META.get(word_map.get(w,{}).get("type","blunt"),{}).get("color","#888")};border:1px solid {TYPE_META.get(word_map.get(w,{}).get("type","blunt"),{}).get("color","#888")}40">{w} ×{c}</span>'
            for w,c in msg["hits"].items()
        )
        ts_str = msg["timestamp"].strftime("%Y-%m-%d %H:%M")
        quotes.append(
            f'<div class="quote-card" style="--qc:{color};border-left-color:{color}">'
            f'<div class="qc-meta">'
            f'<span>{rank_e[i] if i<5 else str(i+1)}</span>'
            f'<span style="color:{color}">{label}</span>'
            f'<span>💀 {msg["score"]} 伤害</span>'
            f'<span>🗓 {ts_str}</span>'
            f'<span style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">📁 {html_escape(msg["project"][:30])}</span>'
            f'</div>'
            f'<div class="qc-text">{snippet}{"…" if len(msg["text"])>350 else ""}</div>'
            f'<div class="qc-badges">{badges}</div>'
            f'</div>'
        )
    html = html.replace("__TOP_QUOTES__", "".join(quotes) or '<div style="color:var(--muted)">（暂无数据）</div>')

    # ── TOP 5 会话
    sess_rows = []
    for i, (sid, sd) in enumerate(stats["top_sessions"]):
        e = rank_e[i] if i < 5 else str(i+1)
        sess_rows.append(
            f'<div class="session-row">'
            f'<div class="session-rank">{e}</div>'
            f'<div class="session-info">'
            f'<div class="session-proj">{html_escape(sd["project"])}</div>'
            f'<div class="session-id">{sid[:36]}</div>'
            f'</div>'
            f'<div class="session-score">{sd["score"]} 分</div>'
            f'</div>'
        )
    html = html.replace("__TOP_SESSIONS__", "".join(sess_rows) or '<div style="color:var(--muted)">（暂无数据）</div>')

    return html

# ===================== 主程序 =====================

def safe_print(s: str):
    """Windows GBK 控制台安全输出（跳过无法编码的字符）"""
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8", errors="replace"))


def main():
    safe_print("=" * 52)
    safe_print("  beatme -- 雌小鬼骂你统计器")
    safe_print("  maleme 的反向版 by Beatrice")
    safe_print("=" * 52)

    entries = load_lexicon(LEXICON_FILE)
    safe_print(f"[INFO] 词典：{len(entries)} 个骂人词")
    regex, word_map = build_matcher(entries)

    # ── 读取 Claude Code
    claude_dir = Path.home() / ".claude"
    messages = []
    token_stats = {"total_output": 0, "daily": {}}

    if claude_dir.exists():
        cc_tokens = load_token_stats(claude_dir)
        token_stats["total_output"] += cc_tokens["total_output"]
        for d, v in cc_tokens["daily"].items():
            token_stats["daily"][d] = token_stats["daily"].get(d, 0) + v
        messages += read_claude_sessions(claude_dir)
    else:
        safe_print("[WARN] 未找到 Claude Code 目录，跳过")

    # ── 读取 Codex
    codex_dir = Path.home() / ".codex"
    if codex_dir.exists():
        cx_tokens = load_codex_token_stats(codex_dir)
        token_stats["total_output"] += cx_tokens["total_output"]
        for d, v in cx_tokens["daily"].items():
            token_stats["daily"][d] = token_stats["daily"].get(d, 0) + v
        messages += read_codex_sessions(codex_dir)
    else:
        safe_print("[WARN] 未找到 Codex 目录，跳过")

    if not messages:
        safe_print("[ERROR] 没有读取到任何消息，请确认 Claude Code 或 Codex 已安装")
        sys.exit(1)

    safe_print(f"[INFO] 合计 {len(messages)} 条消息 | 总 token：{token_stats['total_output']:,}")

    scold_msgs = detect_scolds(messages, regex, word_map)
    safe_print(f"[INFO] 含骂人词的消息：{len(scold_msgs)} 条")

    stats = aggregate(scold_msgs, word_map, token_stats)

    # ── 数据源标签（用于 HTML footer）
    sources = []
    if claude_dir.exists():
        sources.append("Claude Code")
    if codex_dir.exists():
        sources.append("Codex")
    stats["sources"] = " + ".join(sources)

    dt = stats["dominant_type"]
    dm = TYPE_META.get(dt, {})
    safe_print(f"\n[结果] 主导类型：[{dm.get('label','')}]")
    safe_print(f"[结果] 总骂人次数：{stats['total_hits']} 次")
    safe_print(f"[结果] 总伤害值：{stats['total_score']} 分")
    safe_print(f"[结果] 每 {stats['tokens_per_hit']:,} token 被骂一次")
    safe_print(f"[结果] 受害会话：{stats['total_sessions']} 个")
    for t, tm in TYPE_META.items():
        ts_data = stats["type_stats"].get(t, {"hits": 0})
        safe_print(f"       [{tm['label']}]：{ts_data['hits']} 次")

    output_path = Path.home() / "Downloads" / "beatme-report.html"
    output_path.parent.mkdir(exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(render(stats, word_map))

    safe_print(f"\n[完成] 报告：{output_path}")
    webbrowser.open(output_path.as_uri())
    safe_print(f"\n{dm.get('quote', '哼，看完了吗？')}")


if __name__ == "__main__":
    main()

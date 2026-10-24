# -*- coding: utf-8 -*-
"""YouTube 旅游选题扫描器 — RSS+flat 双源 join（零视频详情请求）

用法: python scan.py --out <目录> [--days 30] [--min-views 500000] [--min-duration 480]
"""
import argparse
import json
import os
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

YTDLP = Path.home() / ".workbuddy/binaries/python/envs/default/Scripts/yt-dlp.exe"
SKILL_DIR = Path(__file__).resolve().parent.parent

SEARCH_KWS = [('travel vlog 2026', 1), ('world travel', 1), ('backpacking adventure', 1), ('city tour walking', 2), ('hidden gems city', 2), ('city guide', 2), ('hiking adventure', 3), ('camping wild', 3), ('survival outdoor', 3), ('cultural experience travel', 4), ('living in japan', 4), ('living abroad', 4), ('budget travel tips', 5), ('backpacking cheap', 5), ('hitchhiking', 5), ('luxury hotel review', 6), ('first class flight review', 6), ('resort tour', 6)]

TYPE_NAMES = {1: '环球旅行', 2: '城市探索', 3: '户外冒险', 4: '文化体验', 5: '穷游背包', 6: '奢华度假'}

NS = {
    "a": "http://www.w3.org/2005/Atom",
    "m": "http://search.yahoo.com/mrss/",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run_ytdlp(args, timeout=60):
    try:
        r = subprocess.run(
            [str(YTDLP)] + args,
            capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        if r.returncode == 0:
            return json.loads(r.stdout), None
        return None, (r.stderr or "")[-150:]
    except Exception as e:
        return None, str(e)[:150]


def load_channels():
    channels = []
    with open(SKILL_DIR / "data" / "channels.txt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            channels.append({
                "handle": parts[0],
                "cn_name": parts[1] if len(parts) > 1 else "",
                "type_id": int(parts[2]) if len(parts) > 2 and parts[2] else 0,
            })
    return channels


def resolve_channel_ids(channels):
    cache = {}
    todo = [c for c in channels if c["handle"].lower() not in cache]
    if todo:
        log(f"解析 {len(todo)} 个 handle...")
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {
                ex.submit(run_ytdlp, ["--flat-playlist", "--playlist-items", "1", "-J",
                          f"https://www.youtube.com/{c['handle']}"], 40): c
                for c in todo
            }
            for fut in as_completed(futs):
                c = futs[fut]
                d, _ = fut.result()
                if d and d.get("channel_id"):
                    cache[c["handle"].lower()] = {
                        "channel_id": d["channel_id"],
                        "channel": d.get("channel") or d.get("uploader") or c["cn_name"],
                    }
    for c in channels:
        m = cache.get(c["handle"].lower())
        if m:
            c["channel_id"] = m["channel_id"]
            c["channel"] = m["channel"] or c["cn_name"]
    ok = [c for c in channels if c.get("channel_id")]
    log(f"频道池就绪: {len(ok)}/{len(channels)} 个解析成功")
    return ok


def fetch_rss(cid, timeout=15):
    try:
        req = urllib.request.Request(
            f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        root = ET.fromstring(urllib.request.urlopen(req, timeout=timeout).read())
        out = []
        for e in root.findall("a:entry", NS):
            vid = e.find("yt:videoId", NS)
            pub = e.find("a:published", NS)
            st = e.find(".//m:statistics", NS)
            title = e.find("a:title", NS)
            desc = e.find(".//m:description", NS)
            if vid is None or pub is None or st is None:
                continue
            out.append({
                "video_id": vid.text, "title": (title.text or "").strip(),
                "published": pub.text, "view_count": int(st.get("views") or 0),
                "description": (desc.text or "")[:600] if desc is not None else "",
            })
        return out, None
    except Exception as e:
        return None, str(e)[:120]


def scan_one_channel(c, cutoff, min_views, min_duration):
    ents, err = fetch_rss(c["channel_id"])
    if ents is None:
        return None, f"rss: {err}", []
    url = (f"https://www.youtube.com/{c['handle']}/videos" if c.get("handle")
           else f"https://www.youtube.com/channel/{c['channel_id']}/videos")
    d, _ = run_ytdlp(["--flat-playlist", "--playlist-end", "15", "--no-warnings", "-J", url], 45)
    durs = {}
    if d:
        for e in d.get("entries") or []:
            if isinstance(e, dict) and e.get("id"):
                durs[e["id"]] = e.get("duration")
    hits = []
    for e in ents:
        pub = datetime.fromisoformat(e["published"])
        if pub < cutoff or e["view_count"] < min_views:
            continue
        dur = durs.get(e["video_id"])
        if dur is None or dur < min_duration:
            continue
        hits.append({
            "video_id": e["video_id"], "title": e["title"],
            "channel": c["channel"], "channel_cn": c["cn_name"],
            "url": f"https://www.youtube.com/watch?v={e['video_id']}",
            "thumbnail": f"https://i.ytimg.com/vi/{e['video_id']}/hqdefault.jpg",
            "upload_date": pub.strftime("%Y%m%d"),
            "days_old": (datetime.now(timezone.utc) - pub).days,
            "view_count": e["view_count"], "description": e["description"],
            "type_id": c["type_id"], "cn_type": TYPE_NAMES.get(c["type_id"], "旅游"),
            "source": "channel", "duration_s": dur,
        })
    return hits, None, []


def channel_pass(channels, cutoff, min_views, min_duration, workers=4):
    videos, fails = [], []
    log(f"频道扫描: {len(channels)} 个 × (RSS + flat join)...")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(scan_one_channel, c, cutoff, min_views, min_duration): c for c in channels}
        done = 0
        for fut in as_completed(futs):
            c = futs[fut]; done += 1
            hits, err, _ = fut.result()
            if hits is None: fails.append(c.get("channel") or c["channel_id"])
            else: videos += hits
            if done % 25 == 0: log(f"  频道 {done}/{len(channels)}, 命中 {len(videos)}")
    log(f"频道扫描完成: {len(videos)} 条, 失败 {len(fails)} 频道")
    return videos


def search_pass(min_views, per_kw=30, workers=3):
    discovered = {}
    log(f"搜索: {len(SEARCH_KWS)} 个关键词 × flat{per_kw}, 仅做频道发现...")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_ytdlp, [f"ytsearch{per_kw}:{kw}", "--flat-playlist", "--no-warnings", "-J"], 60): kw
                for kw, _ in SEARCH_KWS}
        for fut in as_completed(futs):
            d, _ = fut.result()
            if not d: continue
            for e in d.get("entries") or []:
                if not isinstance(e, dict) or not e.get("channel_id"): continue
                if (e.get("view_count") or 0) >= min_views:
                    discovered[e["channel_id"]] = e.get("channel") or e.get("uploader") or e["channel_id"]
    log(f"搜索完成: 发现候选频道 {len(discovered)} 个")
    return discovered


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--min-views", type=int, default=500000)
    ap.add_argument("--min-duration", type=int, default=480)
    args = ap.parse_args()
    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    log(f"窗口: 近{args.days}天 | 播放量≥{args.min_views // 10000}万 | 时长≥{args.min_duration // 60}分钟")
    discovered = search_pass(args.min_views)
    base = resolve_channel_ids(load_channels())
    known = {c["channel_id"] for c in base}
    new_chs = [{"handle": None, "cn_name": "", "type_id": 0, "channel_id": cid, "channel": name}
               for cid, name in discovered.items() if cid not in known]
    pool = base + new_chs
    log(f"频道池: {len(pool)} 个 (基础 {len(base)} + 搜索发现 {len(new_chs)})")
    videos = channel_pass(pool, cutoff, args.min_views, args.min_duration)
    if new_chs:
        with open(out_dir / "_channels_discovered.json", "w", encoding="utf-8") as f:
            json.dump([{"channel_id": c["channel_id"], "channel": c["channel"]} for c in new_chs], f, ensure_ascii=False, indent=1)
    videos.sort(key=lambda x: -(x["view_count"] or 0))
    with open(out_dir / "videos_raw.json", "w", encoding="utf-8") as f:
        json.dump(videos, f, ensure_ascii=False, indent=1)
    log(f"✅ {len(videos)} 条候选 → {out_dir / 'videos_raw.json'}")


if __name__ == "__main__":
    main()

"""
公共施設プロジェクト情報 収集スクレイパー
Google News RSS から対象キーワードの記事を取得し data.json に書き出す
"""

import feedparser
import json
import hashlib
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 設定 ──────────────────────────────────────────
JST = timezone(timedelta(hours=9))

# 検索クエリ（Google News RSS）
# 複数ワードはスペース区切りでAND検索になる
SEARCH_QUERIES = [
    "公共施設 再編",
    "公共施設 複合化",
    "公共施設 集約",
    "公共施設 整備計画",
    "公共施設 多機能",
    "公共施設 建設",
    "公共施設 PFI",
    "公共施設 コスト",
    "施設 建築プロジェクト",
    "施設再編 整備",
    "複合施設 建設",
    "PFI 公共 整備",
    "公共建設 コスト 削減",
    "公共施設 集約 複合",
]

# 記事に付与するキーワードタグの定義
# タイトル or 概要にこの文字列が含まれていればタグを付ける
KEYWORD_TAGS = [
    "施設",
    "再編",
    "複合",
    "建築プロジェクト",
    "集約",
    "多機能",
    "整備",
    "コスト",
    "建設",
    "PFI",
]

# 収集対象外ドメイン（広告・まとめサイト等）
BLOCKLIST_DOMAINS = [
    "togetter.com",
    "matome.naver.jp",
    "amazon.co.jp",
]

# 保持する最大記事数
MAX_ARTICLES = 300

# 出力ファイルパス
OUTPUT_PATH = Path(__file__).parent.parent / "data.json"

# ── ユーティリティ ─────────────────────────────────

def make_id(url: str) -> str:
    """URLからユニークIDを生成"""
    return hashlib.md5(url.encode()).hexdigest()[:12]

def parse_date(entry) -> str:
    """feedのdateをJST ISO文字列に変換、失敗したら今日"""
    try:
        import time
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t:
            dt = datetime(*t[:6], tzinfo=timezone.utc).astimezone(JST)
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return datetime.now(JST).strftime("%Y-%m-%d")

def extract_source(entry) -> str:
    """記事ソース名を取得"""
    # Google News RSS は source.title に媒体名が入る
    if hasattr(entry, "source") and hasattr(entry.source, "title"):
        return entry.source.title
    # フィードのタイトルから "(Google ニュース)" を除去
    title = entry.get("title", "")
    if " - " in title:
        return title.split(" - ")[-1].strip()
    return "不明"

def detect_keywords(text: str) -> list[str]:
    """テキスト中に含まれるキーワードタグを検出"""
    found = []
    for kw in KEYWORD_TAGS:
        if kw in text:
            found.append(kw)
    return found

def clean_summary(text: str) -> str:
    """HTMLタグを除去してプレーンテキストに"""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:200]  # 最大200文字

def is_blocked(url: str) -> bool:
    return any(domain in url for domain in BLOCKLIST_DOMAINS)

# ── 収集メイン ─────────────────────────────────────

def fetch_articles() -> list[dict]:
    articles = {}  # id -> article（重複排除用）

    for query in SEARCH_QUERIES:
        encoded = query.replace(" ", "+")
        rss_url = (
            f"https://news.google.com/rss/search"
            f"?q={encoded}"
            f"&hl=ja&gl=JP&ceid=JP:ja"
        )
        print(f"取得中: {query}")
        try:
            feed = feedparser.parse(rss_url)
        except Exception as e:
            print(f"  ⚠️ フィード取得失敗: {e}")
            continue

        for entry in feed.entries:
            url = entry.get("link", "")
            if not url or is_blocked(url):
                continue

            title = entry.get("title", "").strip()
            # Google News のタイトルは "記事タイトル - 媒体名" 形式
            # 媒体名部分を除去してタイトルをクリーン
            source_name = extract_source(entry)
            clean_title = title
            if f" - {source_name}" in title:
                clean_title = title.replace(f" - {source_name}", "").strip()

            summary_raw = entry.get("summary", "") or entry.get("description", "")
            summary = clean_summary(summary_raw)

            full_text = clean_title + " " + summary
            keywords = detect_keywords(full_text)

            # キーワードが1つも引っかからない記事はスキップ
            if not keywords:
                continue

            article_id = make_id(url)
            if article_id not in articles:
                articles[article_id] = {
                    "id":         article_id,
                    "title":      clean_title,
                    "summary":    summary,
                    "url":        url,
                    "source":     "news",
                    "sourceName": source_name,
                    "date":       parse_date(entry),
                    "keywords":   keywords,
                }

        print(f"  → 累計 {len(articles)} 件")

    return list(articles.values())

# ── 既存データとマージ ──────────────────────────────

def merge_with_existing(new_articles: list[dict]) -> list[dict]:
    """既存 data.json と新記事をマージして重複排除・件数制限"""
    existing = []
    if OUTPUT_PATH.exists():
        try:
            data = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
            existing = data.get("articles", [])
        except Exception:
            pass

    # 既存記事をIDでインデックス化
    merged = {a["id"]: a for a in existing}
    # 新記事で上書き（日付更新などに対応）
    for a in new_articles:
        merged[a["id"]] = a

    # 日付降順ソートして件数制限
    result = sorted(merged.values(), key=lambda a: a["date"], reverse=True)
    return result[:MAX_ARTICLES]

# ── 書き出し ───────────────────────────────────────

def save(articles: list[dict]) -> None:
    now_jst = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    payload = {
        "updatedAt": now_jst,
        "count":     len(articles),
        "articles":  articles,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n✅ {len(articles)} 件を {OUTPUT_PATH} に書き出しました（{now_jst} JST）")

# ── エントリポイント ───────────────────────────────

if __name__ == "__main__":
    print("=== 公共施設プロジェクト情報 収集開始 ===\n")
    new_articles = fetch_articles()
    all_articles = merge_with_existing(new_articles)
    save(all_articles)
    print("=== 完了 ===")

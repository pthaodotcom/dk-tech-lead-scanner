"""Local-only Windows dashboard and SQLite store for DK-Tech Lead Scanner."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from contextlib import contextmanager
import hashlib
import json
import re
import sqlite3
import sys
import threading

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rules import DEFAULT_RULES, draft_comment, evaluate, normalize_rules
import comment_writer
import laya_classifier


ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
DATA_DIR = ROOT / ".local" / "dk-tech-lead-scanner"
DB_PATH = DATA_DIR / "scanner.sqlite3"
PAGE_ID = "61593769810301"
DENIED_POST_ID = "1802484360951722"
DENIED_GROUP_ID = "1163787441488087"
MAX_BODY = 12 * 1024 * 1024
MIN_AUTO_INTERVAL_SECONDS = 120
DEFAULT_AUTO_HOURLY_LIMIT = 40
MAX_AUTO_HOURLY_LIMIT = 40
DEFAULT_AUTO_DAILY_LIMIT = 20
MAX_AUTO_DAILY_LIMIT = 200
AUTO_MAX_POST_AGE = timedelta(hours=24)
SERVER_VERSION = "0.7.0"
TEST_TRIGGERED = False
_laya_wake = threading.Event()
_laya_worker_started = False


class AutoWait(ValueError):
    def __init__(self, reason: str, retry_seconds: int = 300):
        super().__init__(reason)
        self.retry_seconds = retry_seconds


def check_auto_limits(db: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc)
    hourly_limit = get_auto_hourly_limit(db)
    daily_limit = get_auto_daily_limit(db)
    # Reservations count too: concurrent callers cannot consume the same quota twice.
    for seconds, limit in [(3600, hourly_limit), (86400, daily_limit)]:
        count = db.execute(
            "SELECT COUNT(*) FROM comment_queue WHERE (attempted_at>=? OR (status='processing' AND created_at>=?))",
            ((now - timedelta(seconds=seconds)).isoformat(),) * 2,
        ).fetchone()[0]
        if count >= limit:
            raise AutoWait(f"Đã đạt giới hạn vận hành {limit} comment/{'giờ' if seconds == 3600 else '24 giờ'}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    return db


@contextmanager
def database():
    db = connect()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with database() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS groups (
              id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', first_seen_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS posts (
              id TEXT PRIMARY KEY, group_id TEXT NOT NULL, group_name TEXT NOT NULL DEFAULT '',
              text TEXT NOT NULL DEFAULT '', url TEXT NOT NULL, text_hash TEXT NOT NULL,
              first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, published_at TEXT, score INTEGER NOT NULL,
              bucket TEXT NOT NULL, reasons TEXT NOT NULL, blocked_reason TEXT,
              review_status TEXT NOT NULL DEFAULT 'unreviewed'
            );
            CREATE INDEX IF NOT EXISTS idx_posts_bucket_seen ON posts(bucket, last_seen_at DESC);
            CREATE TABLE IF NOT EXISTS comment_queue (
              id INTEGER PRIMARY KEY AUTOINCREMENT, post_id TEXT NOT NULL, group_id TEXT NOT NULL,
              message TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
              approved_at TEXT, attempted_at TEXT, result_status TEXT, comment_id TEXT, error TEXT,
              mode TEXT NOT NULL DEFAULT 'manual', reserved_at TEXT, generator TEXT, generation_meta TEXT,
              UNIQUE(post_id, message)
            );
            CREATE TABLE IF NOT EXISTS scan_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, status TEXT NOT NULL,
              groups_count INTEGER NOT NULL, posts_count INTEGER NOT NULL, new_posts INTEGER NOT NULL,
              details TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS denied_posts (
              post_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            """
        )
        queue_columns = {row["name"] for row in db.execute("PRAGMA table_info(comment_queue)")}
        queue_migrations = {
            "mode": "TEXT NOT NULL DEFAULT 'manual'",
            "reserved_at": "TEXT",
            "generator": "TEXT",
            "generation_meta": "TEXT",
        }
        for name, definition in queue_migrations.items():
            if name not in queue_columns:
                db.execute(f"ALTER TABLE comment_queue ADD COLUMN {name} {definition}")
        post_columns = {row["name"] for row in db.execute("PRAGMA table_info(posts)")}
        post_migrations = {
            "published_at": "TEXT",
            "laya_status": "TEXT NOT NULL DEFAULT 'pending'",
            "laya_bucket": "TEXT",
            "laya_label": "TEXT",
            "laya_confidence": "REAL",
            "laya_service": "TEXT",
            "laya_safety": "TEXT",
            "laya_result": "TEXT",
            "laya_at": "TEXT",
        }
        for name, definition in post_migrations.items():
            if name not in post_columns:
                db.execute(f"ALTER TABLE posts ADD COLUMN {name} {definition}")
        db.execute("CREATE INDEX IF NOT EXISTS idx_posts_laya_status ON posts(laya_status, published_at DESC)")
        group_columns = {row["name"] for row in db.execute("PRAGMA table_info(groups)")}
        if "scan_enabled" not in group_columns:
            db.execute("ALTER TABLE groups ADD COLUMN scan_enabled INTEGER NOT NULL DEFAULT 1")
        if "comment_enabled" not in group_columns:
            db.execute("ALTER TABLE groups ADD COLUMN comment_enabled INTEGER NOT NULL DEFAULT 1")
        db.execute(
            "INSERT OR IGNORE INTO denied_posts(post_id,group_id,reason,created_at) VALUES(?,?,?,?)",
            (DENIED_POST_ID, DENIED_GROUP_ID, "Bài data game/cờ bạc do chủ tool yêu cầu cấm gửi", utc_now()),
        )
        db.execute(
            "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES('filter_rules',?,?)",
            (json.dumps(DEFAULT_RULES, ensure_ascii=False), utc_now()),
        )
        db.execute(
            "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES('auto_hourly_limit',?,?)",
            (str(DEFAULT_AUTO_HOURLY_LIMIT), utc_now()),
        )
        db.execute(
            "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES('auto_daily_limit',?,?)",
            (str(DEFAULT_AUTO_DAILY_LIMIT), utc_now()),
        )


def row_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def get_filter_rules(db: sqlite3.Connection | None = None) -> dict:
    if db is None:
        with database() as connection:
            return get_filter_rules(connection)
    row = db.execute("SELECT value FROM settings WHERE key='filter_rules'").fetchone()
    return normalize_rules(json.loads(row["value"]) if row else DEFAULT_RULES)


def save_filter_rules(payload: dict) -> dict:
    config = normalize_rules(payload)
    now = utc_now()
    with database() as db:
        db.execute(
            "INSERT INTO settings(key,value,updated_at) VALUES('filter_rules',?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (json.dumps(config, ensure_ascii=False), now),
        )
        rows = db.execute("SELECT id,text FROM posts").fetchall()
        for row in rows:
            result = evaluate(row["text"], config)
            db.execute(
                "UPDATE posts SET score=?,bucket=?,reasons=?,blocked_reason=? WHERE id=?",
                (result["score"], result["bucket"], json.dumps(result["reasons"], ensure_ascii=False),
                 result.get("blocked_reason"), row["id"]),
            )
    return {"rules": config, "reevaluatedPosts": len(rows)}


def normalize_auto_hourly_limit(value: object) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = DEFAULT_AUTO_HOURLY_LIMIT
    return max(1, min(limit, MAX_AUTO_HOURLY_LIMIT))


def get_auto_hourly_limit(db: sqlite3.Connection | None = None) -> int:
    if db is None:
        with database() as connection:
            return get_auto_hourly_limit(connection)
    row = db.execute("SELECT value FROM settings WHERE key='auto_hourly_limit'").fetchone()
    return normalize_auto_hourly_limit(row["value"] if row else DEFAULT_AUTO_HOURLY_LIMIT)


def normalize_auto_daily_limit(value: object) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = DEFAULT_AUTO_DAILY_LIMIT
    return max(1, min(limit, MAX_AUTO_DAILY_LIMIT))


def get_auto_daily_limit(db: sqlite3.Connection | None = None) -> int:
    if db is None:
        with database() as connection:
            return get_auto_daily_limit(connection)
    row = db.execute("SELECT value FROM settings WHERE key='auto_daily_limit'").fetchone()
    return normalize_auto_daily_limit(row["value"] if row else DEFAULT_AUTO_DAILY_LIMIT)


def save_auto_settings(payload: dict) -> dict:
    hourly_limit = normalize_auto_hourly_limit(payload.get("hourlyLimit"))
    daily_limit = normalize_auto_daily_limit(payload.get("dailyLimit"))
    with database() as db:
        db.execute(
            "INSERT INTO settings(key,value,updated_at) VALUES('auto_hourly_limit',?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (str(hourly_limit), utc_now()),
        )
        db.execute(
            "INSERT INTO settings(key,value,updated_at) VALUES('auto_daily_limit',?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (str(daily_limit), utc_now()),
        )
    return {"hourlyLimit": hourly_limit, "dailyLimit": daily_limit,
            "maximumHourlyLimit": MAX_AUTO_HOURLY_LIMIT, "maximumDailyLimit": MAX_AUTO_DAILY_LIMIT}


def get_groups_config() -> dict:
    with database() as db:
        groups = [dict(row) for row in db.execute(
            """SELECT g.id, g.name, g.scan_enabled, g.comment_enabled,
                      g.first_seen_at, g.last_seen_at,
                      (SELECT COUNT(*) FROM posts p WHERE p.group_id=g.id) AS post_count
               FROM groups g
               ORDER BY g.scan_enabled DESC, g.name ASC, g.id ASC"""
        )]
    return {"groups": groups}


def save_group_config(payload: dict) -> dict:
    action = payload.get("action")
    with database() as db:
        if action == "enable_all_scan":
            db.execute("UPDATE groups SET scan_enabled=1")
        elif action == "disable_all_scan":
            db.execute("UPDATE groups SET scan_enabled=0")
        elif action == "enable_all_comment":
            db.execute("UPDATE groups SET comment_enabled=1")
        elif action == "disable_all_comment":
            db.execute("UPDATE groups SET comment_enabled=0")
        elif "groups" in payload and isinstance(payload["groups"], list):
            for item in payload["groups"]:
                gid = str(item.get("id", ""))
                if not gid.isdigit():
                    continue
                scan_en = 1 if item.get("scan_enabled", item.get("scanEnabled", True)) else 0
                cmt_en = 1 if item.get("comment_enabled", item.get("commentEnabled", True)) else 0
                db.execute(
                    "UPDATE groups SET scan_enabled=?, comment_enabled=? WHERE id=?",
                    (scan_en, cmt_en, gid),
                )
        elif "groupId" in payload or "id" in payload:
            gid = str(payload.get("groupId") or payload.get("id"))
            if gid.isdigit():
                updates = []
                params = []
                if "scanEnabled" in payload or "scan_enabled" in payload:
                    val = 1 if payload.get("scanEnabled", payload.get("scan_enabled")) else 0
                    updates.append("scan_enabled=?")
                    params.append(val)
                if "commentEnabled" in payload or "comment_enabled" in payload:
                    val = 1 if payload.get("commentEnabled", payload.get("comment_enabled")) else 0
                    updates.append("comment_enabled=?")
                    params.append(val)
                if updates:
                    params.append(gid)
                    db.execute(f"UPDATE groups SET {','.join(updates)} WHERE id=?", tuple(params))
    return {"saved": True}


def ingest(payload: dict) -> dict:
    if str(payload.get("actingPageId", "")) != PAGE_ID:
        raise ValueError("Sai Page đang hoạt động")
    groups = payload.get("groups") if isinstance(payload.get("groups"), list) else []
    posts = payload.get("posts") if isinstance(payload.get("posts"), list) else []
    if len(groups) > 500 or len(posts) > 5000:
        raise ValueError("Dữ liệu quét vượt giới hạn")
    now = utc_now()
    new_posts = 0
    with database() as db:
        filter_rules = get_filter_rules(db)
        denied = {row["post_id"] for row in db.execute("SELECT post_id FROM denied_posts")}
        for group in groups:
            gid = str(group.get("id", ""))
            if not gid.isdigit():
                continue
            name = str(group.get("name", ""))[:200]
            db.execute(
                """INSERT INTO groups(id,name,first_seen_at,last_seen_at,scan_enabled,comment_enabled) VALUES(?,?,?,?,1,1)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name,last_seen_at=excluded.last_seen_at""",
                (gid, name, now, now),
            )
        for post in posts:
            pid = str(post.get("postId", ""))
            gid = str(post.get("groupId", ""))
            if not pid.isdigit() or not gid.isdigit():
                continue
            text = str(post.get("text", ""))[:20000]
            group_name = str(post.get("groupName", ""))[:200]
            published_at = str(post.get("publishedAt") or "").strip() or None
            result = evaluate(text, filter_rules)
            if pid in denied:
                result = {"score": -100, "bucket": "blocked", "reasons": ["Bài nằm trong denylist"],
                          "blocked_reason": "denylist"}
            text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            exists = db.execute("SELECT text_hash FROM posts WHERE id=?", (pid,)).fetchone()
            if not exists:
                new_posts += 1
            url = f"https://www.facebook.com/groups/{gid}/posts/{pid}/"
            db.execute(
                """INSERT INTO posts(id,group_id,group_name,text,url,text_hash,first_seen_at,last_seen_at,published_at,
                                      score,bucket,reasons,blocked_reason)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET group_id=excluded.group_id,group_name=excluded.group_name,
                     text=excluded.text,url=excluded.url,text_hash=excluded.text_hash,last_seen_at=excluded.last_seen_at,
                   published_at=COALESCE(excluded.published_at,posts.published_at),
                   score=excluded.score,bucket=excluded.bucket,reasons=excluded.reasons,
                     blocked_reason=excluded.blocked_reason,
                     laya_status=CASE WHEN posts.text_hash<>excluded.text_hash THEN 'pending' ELSE posts.laya_status END,
                     laya_bucket=CASE WHEN posts.text_hash<>excluded.text_hash THEN NULL ELSE posts.laya_bucket END,
                     laya_label=CASE WHEN posts.text_hash<>excluded.text_hash THEN NULL ELSE posts.laya_label END,
                     laya_confidence=CASE WHEN posts.text_hash<>excluded.text_hash THEN NULL ELSE posts.laya_confidence END,
                     laya_service=CASE WHEN posts.text_hash<>excluded.text_hash THEN NULL ELSE posts.laya_service END,
                     laya_safety=CASE WHEN posts.text_hash<>excluded.text_hash THEN NULL ELSE posts.laya_safety END,
                     laya_result=CASE WHEN posts.text_hash<>excluded.text_hash THEN NULL ELSE posts.laya_result END,
                     laya_at=CASE WHEN posts.text_hash<>excluded.text_hash THEN NULL ELSE posts.laya_at END""",
                (pid, gid, group_name, text, url, text_hash, now, now, published_at, result["score"], result["bucket"],
                 json.dumps(result["reasons"], ensure_ascii=False), result.get("blocked_reason")),
            )
        details = {
            "queryCompatibility": payload.get("compatibility"),
            "completedGroups": payload.get("completedGroups"),
            "truncatedGroups": payload.get("truncatedGroups"),
            "failedGroups": payload.get("failedGroups"),
            "source": "chrome_extension",
        }
        db.execute(
            "INSERT INTO scan_runs(started_at,status,groups_count,posts_count,new_posts,details) VALUES(?,?,?,?,?,?)",
            (now, str(payload.get("status", "PASS"))[:40], len(groups), len(posts), new_posts,
             json.dumps(details, ensure_ascii=False)),
        )
    _laya_wake.set()
    return {"saved": len(posts), "newPosts": new_posts, "groups": len(groups)}


def classify_next_laya_post() -> bool:
    """Claim and classify one recent, unblocked post outside the HTTP request path."""
    cutoff = (datetime.now(timezone.utc) - AUTO_MAX_POST_AGE).isoformat()
    with database() as db:
        row = db.execute(
            """SELECT id,text,text_hash FROM posts
               WHERE laya_status='pending' AND bucket!='blocked' AND TRIM(text)!=''
                 AND published_at IS NOT NULL AND datetime(published_at)>=datetime(?)
               ORDER BY datetime(published_at) DESC LIMIT 1""", (cutoff,)
        ).fetchone()
        if not row:
            return False
        post_id = row["id"]
        changed = db.execute(
            "UPDATE posts SET laya_status='processing',laya_result=NULL WHERE id=? AND laya_status='pending'",
            (post_id,),
        ).rowcount
        if not changed:
            return True
        text = row["text"]
        text_hash = row["text_hash"]

    try:
        result = laya_classifier.classify(text)
        with database() as db:
            db.execute(
                """UPDATE posts SET laya_status=?,laya_bucket=?,laya_label=?,laya_confidence=?,
                     laya_service=?,laya_safety=?,laya_result=?,laya_at=?
                   WHERE id=? AND text_hash=? AND laya_status='processing'""",
                (result["status"], result["bucket"], result["label"], result["confidence"],
                 result["service"], result["safety"], json.dumps(result, ensure_ascii=False), utc_now(), post_id,
                 text_hash),
            )
    except Exception as exc:
        failure = {"error": f"{type(exc).__name__}: {exc}"}
        with database() as db:
            db.execute(
                """UPDATE posts SET laya_status='failed',laya_bucket='uncertain',laya_result=?,laya_at=?
                   WHERE id=? AND text_hash=? AND laya_status='processing'""",
                (json.dumps(failure, ensure_ascii=False), utc_now(), post_id, text_hash),
            )
    return True


def laya_worker() -> None:
    while True:
        try:
            found = classify_next_laya_post()
        except Exception as exc:
            print(f"Laya worker error: {type(exc).__name__}: {exc}", flush=True)
            found = False
        if not found:
            _laya_wake.wait(2)
            _laya_wake.clear()


def start_laya_worker() -> None:
    global _laya_worker_started
    if _laya_worker_started:
        return
    _laya_worker_started = True
    with database() as db:
        db.execute("UPDATE posts SET laya_status='pending' WHERE laya_status IN ('processing','failed')")
        version_row = db.execute("SELECT value FROM settings WHERE key='laya_classifier_version'").fetchone()
        if not version_row or version_row["value"] != laya_classifier.CLASSIFIER_VERSION:
            db.execute("UPDATE posts SET laya_status='pending' WHERE laya_status='done'")
            db.execute(
                "INSERT INTO settings(key,value,updated_at) VALUES('laya_classifier_version',?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                (laya_classifier.CLASSIFIER_VERSION, utc_now()),
            )
    threading.Thread(target=laya_worker, name="dktech-laya-worker", daemon=True).start()
    _laya_wake.set()


def dashboard_data(bucket: str = "all") -> dict:
    recent_cutoff = (datetime.now(timezone.utc) - AUTO_MAX_POST_AGE).isoformat()
    where = "WHERE p.published_at IS NOT NULL AND datetime(p.published_at) >= datetime(?)"
    params: tuple[str, ...] = (recent_cutoff,)
    if bucket != "all":
        where += " AND p.bucket=?"
        params += (bucket,)
    with database() as db:
        filter_rules = get_filter_rules(db)
        posts = []
        for row in db.execute(
            f"""SELECT p.*,
                (SELECT status FROM comment_queue q WHERE q.post_id=p.id ORDER BY q.id DESC LIMIT 1) queue_status
                FROM posts p {where}
                ORDER BY datetime(COALESCE(p.published_at, p.first_seen_at)) DESC, p.score DESC
                LIMIT 300""", params
        ):
            item = dict(row)
            item["reasons"] = json.loads(item["reasons"] or "[]")
            try:
                laya_result = json.loads(item["laya_result"] or "{}")
            except (TypeError, json.JSONDecodeError):
                laya_result = {}
            item["laya_post_type"] = (laya_result.get("postType") or "unknown")
            item["laya_post_type_confidence"] = (laya_result.get("confidences") or {}).get("post_type")
            item["laya_post_type_minimum_confidence"] = laya_result.get("postTypeMinimumConfidence", .6)
            item['laya_service_confidence']=(laya_result.get('confidences') or {}).get('service')
            item['laya_safety_confidence']=(laya_result.get('confidences') or {}).get('safety')
            item['laya_decision_reasons']=laya_result.get('decisionReasons') or []
            item['laya_safety_review']=laya_result.get('safetyNeedsReview',False)
            posts.append(item)
        counts = {row["bucket"]: row["n"] for row in db.execute(
            """SELECT bucket,COUNT(*) n FROM posts
               WHERE published_at IS NOT NULL AND datetime(published_at) >= datetime(?) GROUP BY bucket""",
            (recent_cutoff,),
        )}
        laya_stats = {row["laya_status"]: row["n"] for row in db.execute(
            """SELECT laya_status,COUNT(*) n FROM posts
               WHERE published_at IS NOT NULL AND datetime(published_at)>=datetime(?) GROUP BY laya_status""",
            (recent_cutoff,),
        )}
        latest = row_dict(db.execute("SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone())
        queue = [dict(row) for row in db.execute(
            """SELECT q.*,p.url,p.group_name,p.text post_text
               FROM comment_queue q LEFT JOIN posts p ON p.id=q.post_id
               ORDER BY q.id DESC LIMIT 100"""
        )]
        group_row = db.execute(
            """SELECT COUNT(*) total,
                      COALESCE(SUM(CASE WHEN scan_enabled=1 THEN 1 ELSE 0 END), 0) scan_enabled,
                      COALESCE(SUM(CASE WHEN comment_enabled=1 THEN 1 ELSE 0 END), 0) comment_enabled
               FROM groups"""
        ).fetchone()
        group_stats = {
            "total": (group_row["total"] or 0) if group_row else 0,
            "scanEnabled": (group_row["scan_enabled"] or 0) if group_row else 0,
            "commentEnabled": (group_row["comment_enabled"] or 0) if group_row else 0,
        }
        auto_eligible_count = sum(
            auto_eligibility(row, filter_rules)[0] for row in db.execute(
                """SELECT p.* FROM posts p
                   LEFT JOIN groups g ON g.id=p.group_id
                   LEFT JOIN denied_posts d ON d.post_id=p.id
                   WHERE p.review_status='unreviewed' AND d.post_id IS NULL
                     AND COALESCE(g.comment_enabled, 1)=1
                     AND NOT EXISTS (SELECT 1 FROM comment_queue q WHERE q.post_id=p.id)"""
            )
        )
    return {"pageId": PAGE_ID, "posts": posts, "counts": counts, "latestScan": latest,
            "queue": queue, "filterRules": filter_rules, "groupStats": group_stats,
            "autoEligibleCount": auto_eligible_count, "commentWriter": comment_writer.status(),
            "layaClassifier": laya_classifier.status(), "layaStats": laya_stats}


def approve_comment(post_id: str, message: str | None) -> dict:
    with database() as db:
        post = db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
        if not post:
            raise ValueError("Không tìm thấy bài")
        denied = db.execute("SELECT reason FROM denied_posts WHERE post_id=?", (post_id,)).fetchone()
        if denied or post["bucket"] == "blocked":
            raise ValueError("Bài bị chặn; không thể tạo hàng đợi comment")
        text = (message or draft_comment(post["text"])).strip()
        if not 5 <= len(text) <= 500:
            raise ValueError("Comment phải dài 5-500 ký tự")
        now = utc_now()
        db.execute(
            """INSERT INTO comment_queue(post_id,group_id,message,status,created_at,approved_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(post_id,message) DO UPDATE SET status='approved',approved_at=excluded.approved_at,
                 result_status=NULL,comment_id=NULL,error=NULL""",
            (post_id, post["group_id"], text, "approved", now, now),
        )
        db.execute("UPDATE posts SET review_status='approved' WHERE id=?", (post_id,))
        row = db.execute(
            "SELECT * FROM comment_queue WHERE post_id=? AND message=?", (post_id, text)
        ).fetchone()
    return dict(row)


def auto_eligibility(post: sqlite3.Row | dict, config: dict | None = None) -> tuple[bool, str]:
    """Apply the owner's current filter rules before reserving a post."""
    item = dict(post)
    if item.get("bucket") == "blocked" or item.get("blocked_reason"):
        return False, "rule_blocked"
    if item.get("laya_status") != "done":
        return False, "laya_" + str(item.get("laya_status") or "pending")
    if item.get("laya_bucket") != "qualified":
        return False, "laya_not_qualified"
    if not (item.get("text") or "").strip():
        return False, "empty_post"
    published_at = item.get("published_at")
    try:
        published = datetime.fromisoformat(str(published_at))
        if published.tzinfo is None:
            return False, "missing_published_at"
    except (TypeError, ValueError):
        return False, "missing_published_at"
    if datetime.now(timezone.utc) - published.astimezone(timezone.utc) > AUTO_MAX_POST_AGE:
        return False, "older_than_24_hours"
    rules = normalize_rules(config) if config else get_filter_rules()
    if item.get("bucket") != "candidate" and not rules["includeUnmatched"]:
        return False, "unmatched"
    return True, "eligible"


def reserve_auto_comment() -> dict | None:
    """Atomically reserve one rule-eligible, never-attempted post."""
    now = utc_now()
    with database() as db:
        filter_rules = get_filter_rules(db)
        check_auto_limits(db)
        recent = db.execute(
            "SELECT attempted_at FROM comment_queue WHERE mode='auto' AND attempted_at IS NOT NULL "
            "ORDER BY attempted_at DESC LIMIT 1"
        ).fetchone()
        if recent:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(recent["attempted_at"])).total_seconds()
            if elapsed < MIN_AUTO_INTERVAL_SECONDS:
                raise AutoWait(f"Cần chờ thêm {int(MIN_AUTO_INTERVAL_SECONDS - elapsed) + 1} giây",
                               int(MIN_AUTO_INTERVAL_SECONDS - elapsed) + 1)
        rows = db.execute(
            """SELECT p.* FROM posts p
               LEFT JOIN groups g ON g.id=p.group_id
               LEFT JOIN denied_posts d ON d.post_id=p.id
               WHERE d.post_id IS NULL AND p.review_status='unreviewed'
                 AND COALESCE(g.comment_enabled, 1)=1
                 AND NOT EXISTS (SELECT 1 FROM comment_queue q WHERE q.post_id=p.id)
               ORDER BY datetime(COALESCE(p.published_at, p.first_seen_at)) DESC, p.score DESC"""
        ).fetchall()
        post = None
        group_wait = None
        for row in rows:
            if not auto_eligibility(row, filter_rules)[0]:
                continue
            try:
                check_auto_limits(db)
            except AutoWait as exc:
                group_wait = exc
                continue
            post = row
            break
        if not post:
            if group_wait:
                raise group_wait
            return None
        post = dict(post)
    generated = comment_writer.generate(post["text"])
    text = generated["comment"]
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        check_auto_limits(db)
        still_available = db.execute(
            """SELECT p.* FROM posts p
               LEFT JOIN groups g ON g.id=p.group_id
               LEFT JOIN denied_posts d ON d.post_id=p.id
               WHERE p.id=? AND d.post_id IS NULL AND p.review_status='unreviewed'
                 AND COALESCE(g.comment_enabled, 1)=1
                 AND NOT EXISTS (SELECT 1 FROM comment_queue q WHERE q.post_id=p.id)""",
            (post["id"],),
        ).fetchone()
        if not still_available or not auto_eligibility(still_available, filter_rules)[0]:
            raise ValueError("Bài vừa được xử lý ở tiến trình khác")
        cursor = db.execute(
            """INSERT INTO comment_queue(post_id,group_id,message,status,created_at,approved_at,mode,reserved_at,
                                          generator,generation_meta)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (post["id"], post["group_id"], text, "processing", now, now, "auto", now,
             generated["model"], json.dumps({"generation": generated}, ensure_ascii=False)),
        )
        db.execute("UPDATE posts SET review_status='auto_processing' WHERE id=?", (post["id"],))
        row = db.execute(
            """SELECT q.*,p.url,p.group_name,p.text FROM comment_queue q
               JOIN posts p ON p.id=q.post_id WHERE q.id=?""", (cursor.lastrowid,)
        ).fetchone()
    return row_dict(row)


def next_comment() -> dict | None:
    with database() as db:
        row = db.execute(
            """SELECT q.*,p.url,p.group_name,p.text FROM comment_queue q JOIN posts p ON p.id=q.post_id
               LEFT JOIN denied_posts d ON d.post_id=q.post_id
               WHERE q.status='approved' AND d.post_id IS NULL AND p.bucket!='blocked'
               ORDER BY q.approved_at ASC,q.id ASC LIMIT 1"""
        ).fetchone()
    return row_dict(row)


def save_comment_result(payload: dict) -> dict:
    queue_id = int(payload.get("queueId", 0))
    status = str(payload.get("status", "INCONCLUSIVE"))[:50]
    comment_id = str(payload.get("commentId") or "")[:80] or None
    error = str(payload.get("error") or payload.get("reason") or "")[:500] or None
    with database() as db:
        row = db.execute("SELECT * FROM comment_queue WHERE id=?", (queue_id,)).fetchone()
        if not row:
            raise ValueError("Không tìm thấy hàng đợi")
        if status == "SKIPPED_COMMENT_DISABLED":
            final = "skipped"
        elif status in {"SUBMITTED_REJECTED", "SUBMITTED_PENDING", "SUBMITTED_UNVERIFIED"} and payload.get("submitted") is True:
            final = {"SUBMITTED_REJECTED": "sent_rejected", "SUBMITTED_PENDING": "sent_pending",
                     "SUBMITTED_UNVERIFIED": "sent_unverified"}[status]
        else:
            final = "sent" if comment_id and status.startswith("PASS") else "blocked" if status == "BLOCKED" else "attempted"
        attempted_at = row["attempted_at"] or (None if final in {"blocked", "skipped"} else utc_now())
        db.execute(
            "UPDATE comment_queue SET status=?,attempted_at=?,result_status=?,comment_id=?,error=? WHERE id=?",
            (final, attempted_at, status, comment_id, error, queue_id),
        )
        db.execute("UPDATE posts SET review_status=? WHERE id=?", (final, row["post_id"]))
    return {"saved": True, "queueId": queue_id, "status": final}


def mark_comment_attempt(payload: dict) -> dict:
    queue_id = int(payload.get("queueId", 0))
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM comment_queue WHERE id=?", (queue_id,)).fetchone()
        if not row or row["status"] != "processing" or row["attempted_at"]:
            raise ValueError("Comment đã thử gửi hoặc không còn trong lượt xử lý")
        db.execute("UPDATE comment_queue SET status='attempted',attempted_at=?,result_status='INCONCLUSIVE' WHERE id=?",
                   (utc_now(), queue_id))
        db.execute("UPDATE posts SET review_status='attempted' WHERE id=?", (row["post_id"],))
    return {"recorded": True, "queueId": queue_id}


def release_auto_comment(payload: dict) -> dict:
    """Put an unattempted auto reservation back when browser preflight cannot send it."""
    queue_id = int(payload.get("queueId", 0))
    diagnostics = payload.get("diagnostics")
    if diagnostics:
        try:
            print(f"[COMPOSER_DIAGNOSTICS] {json.dumps(diagnostics, ensure_ascii=False)}", flush=True)
            comp = diagnostics.get("comparison") or {}
            if comp:
                min_c = comp.get("MINIMIZED", {})
                norm_c = comp.get("NORMAL", {})
                print(f"[COMPOSER_PROBE_COMPARISON]\nMINIMIZED\ndocument.visibilityState={min_c.get('documentVisibilityState')}\ncontenteditableCount={min_c.get('contenteditableCount')}\ntextboxCount={min_c.get('textboxCount')}\ncomposerCandidateCount={min_c.get('composerCandidateCount')}\ntargetComposer={min_c.get('targetComposer')}\nrectCount={min_c.get('rectCount')}\n\nNORMAL\ndocument.visibilityState={norm_c.get('documentVisibilityState')}\ncontenteditableCount={norm_c.get('contenteditableCount')}\ntextboxCount={norm_c.get('textboxCount')}\ncomposerCandidateCount={norm_c.get('composerCandidateCount')}\ntargetComposer={norm_c.get('targetComposer')}\nrectCount={norm_c.get('rectCount')}", flush=True)
            for cand in diagnostics.get("candidatesFormatted") or []:
                print(f"--- CANDIDATE ---\n{cand}", flush=True)
            scope_d = diagnostics.get("scopeDetails") or {}
            if scope_d:
                print(f"[SCOPE_SNIPPET] {scope_d.get('textSnippet')}", flush=True)
                for el in scope_d.get("commentElements") or []:
                    print(f"[SCOPE_COMMENT_EL] {json.dumps(el, ensure_ascii=False)}", flush=True)
        except Exception:
            try:
                print(f"[COMPOSER_DIAGNOSTICS] {json.dumps(diagnostics, ensure_ascii=True)}", flush=True)
            except Exception:
                pass
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT post_id FROM comment_queue WHERE id=? AND mode='auto' "
            "AND status='processing' AND attempted_at IS NULL", (queue_id,),
        ).fetchone()
        if not row:
            return {"released": False, "queueId": queue_id}
        db.execute("DELETE FROM comment_queue WHERE id=?", (queue_id,))
        db.execute(
            "UPDATE posts SET review_status='unreviewed' WHERE id=? AND review_status='auto_processing'",
            (row["post_id"],),
        )
    return {"released": True, "queueId": queue_id}


def clear_pending_comments() -> dict:
    """Reset the scan backlog while retaining groups, rules, and denylist settings."""
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        deleted_posts = db.execute("DELETE FROM posts").rowcount
        deleted_scans = db.execute("DELETE FROM scan_runs").rowcount
    return {"deletedPosts": deleted_posts, "deletedScans": deleted_scans}


class Handler(BaseHTTPRequestHandler):
    server_version = "DKTechLeadScanner/0.1"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def extension_origin(self) -> str | None:
        origin = self.headers.get("Origin", "")
        return origin if re.fullmatch(r"chrome-extension://[a-p]{32}", origin) else None

    def send_json(self, status: int, value: dict | list) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        origin = self.extension_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= MAX_BODY:
            raise ValueError("Kích thước request không hợp lệ")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("JSON phải là object")
        return value

    def serve_static(self, name: str, content_type: str) -> None:
        path = STATIC / name
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        if not self.extension_origin():
            self.send_json(403, {"error": "Origin không được phép"})
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.extension_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self.serve_static("index.html", "text/html; charset=utf-8")
            elif parsed.path == "/app.js":
                self.serve_static("app.js", "text/javascript; charset=utf-8")
            elif parsed.path == "/style.css":
                self.serve_static("style.css", "text/css; charset=utf-8")
            elif parsed.path == "/health":
                self.send_json(200, {"status": "ready", "pageId": PAGE_ID, "facebookAccess": False,
                                     "layaClassifier": laya_classifier.status(),
                                     "commentWriter": comment_writer.status()})
            elif parsed.path == "/api/version":
                self.send_json(200, {"service": "dktech-comment-backend", "version": SERVER_VERSION})
            elif parsed.path == "/api/dashboard":
                bucket = parse_qs(parsed.query).get("bucket", ["all"])[0]
                self.send_json(200, dashboard_data(bucket))
            elif parsed.path == "/api/scan-groups":
                include_all = parse_qs(parsed.query).get("all", ["0"])[0] == "1"
                condition = "" if include_all else "WHERE scan_enabled=1"
                with database() as db:
                    groups = [dict(row) for row in db.execute(
                        f"SELECT id,name FROM groups {condition} ORDER BY last_seen_at DESC, id ASC"
                    )]
                self.send_json(200, {"groups": groups})
            elif parsed.path == "/api/groups":
                self.send_json(200, get_groups_config())
            elif parsed.path == "/api/comments/next":
                self.send_json(200, {"item": next_comment()})
            elif parsed.path == "/api/comments/trigger-check":
                global TEST_TRIGGERED
                was_triggered = TEST_TRIGGERED
                TEST_TRIGGERED = False
                self.send_json(200, {"trigger": was_triggered})
            elif parsed.path == "/api/rules":
                self.send_json(200, {"rules": get_filter_rules()})
            elif parsed.path == "/api/automation-settings":
                self.send_json(200, {"hourlyLimit": get_auto_hourly_limit(), "dailyLimit": get_auto_daily_limit(),
                                     "maximumHourlyLimit": MAX_AUTO_HOURLY_LIMIT,
                                     "maximumDailyLimit": MAX_AUTO_DAILY_LIMIT})
            else:
                self.send_json(404, {"error": "Không tìm thấy"})
        except (ValueError, sqlite3.Error) as exc:
            self.send_json(400, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
            if parsed.path == "/api/scan-ingest":
                self.send_json(200, ingest(payload))
            elif parsed.path == "/api/groups/config":
                self.send_json(200, save_group_config(payload))
            elif parsed.path == "/api/rules":
                self.send_json(200, save_filter_rules(payload))
            elif parsed.path == "/api/automation-settings":
                self.send_json(200, save_auto_settings(payload))
            elif parsed.path.startswith("/api/posts/") and parsed.path.endswith("/approve"):
                post_id = parsed.path.split("/")[3]
                self.send_json(200, approve_comment(post_id, payload.get("message")))
            elif parsed.path == "/api/comments/auto-next":
                try:
                    self.send_json(200, {"item": reserve_auto_comment()})
                except AutoWait as exc:
                    self.send_json(200, {"item": None, "waitReason": str(exc), "retrySeconds": exc.retry_seconds})
            elif parsed.path == "/api/comments/trigger-test":
                global TEST_TRIGGERED
                TEST_TRIGGERED = True
                self.send_json(200, {"triggered": True})
            elif parsed.path == "/api/comments/result":
                self.send_json(200, save_comment_result(payload))
            elif parsed.path == "/api/comments/attempt":
                self.send_json(200, mark_comment_attempt(payload))
            elif parsed.path == "/api/comments/release":
                self.send_json(200, release_auto_comment(payload))
            elif parsed.path == "/api/comments/clear-pending":
                self.send_json(200, clear_pending_comments())
            elif parsed.path == "/api/shutdown":
                self.send_json(200, {"stopping": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self.send_json(404, {"error": "Không tìm thấy"})
        except (ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
            self.send_json(400, {"error": str(exc)})
        except RuntimeError as exc:
            self.send_json(502, {"error": str(exc)})


if __name__ == "__main__":
    init_db()
    start_laya_worker()
    routes = [
        "GET  /",
        "GET  /app.js",
        "GET  /style.css",
        "GET  /health",
        "GET  /api/version",
        "GET  /api/dashboard",
        "GET  /api/scan-groups",
        "GET  /api/groups",
        "GET  /api/comments/next",
        "GET  /api/rules",
        "GET  /api/automation-settings",
        "POST /api/scan-ingest",
        "POST /api/groups/config",
        "POST /api/posts/<id>/approve",
        "POST /api/comments/auto-next",
        "POST /api/comments/result",
        "POST /api/comments/attempt",
        "POST /api/comments/release",
        "POST /api/comments/clear-pending",
        "POST /api/rules",
        "POST /api/automation-settings",
        "POST /api/shutdown",
    ]
    server = ThreadingHTTPServer(("127.0.0.1", 9350), Handler)
    print(f"DK-Tech Lead Scanner v{SERVER_VERSION}: http://127.0.0.1:9350", flush=True)
    print("Registered routes:\n  " + "\n  ".join(routes), flush=True)
    server.serve_forever()

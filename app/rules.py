"""User-configurable first-pass filtering for DK-Tech lead posts."""

import re
import unicodedata


DEFAULT_RULES = {
    "includeKeywords": [
        "website", "trang web", "landing page", "web bán hàng", "thiết kế web",
        "phần mềm", "ứng dụng", "app", "crm", "erp", "quản lý", "tool", "bot",
        "tự động", "automation", "api", "tích hợp", "crawl", "cần tìm", "cần làm",
        "cần thuê", "tìm người", "tìm bên", "ai làm", "báo giá", "triển khai",
        "xây dựng", "code thuê", "đơn vị nào", "bên nào",
    ],
    "excludeKeywords": [
        "cờ bạc", "cá cược", "casino", "tài xỉu", "game bài", "đánh bạc", "lô đề",
        "nhà cái", "soi kèo", "data game",
    ],
    "minimumMatches": 1,
    "includeUnmatched": True,
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFC", value or "").lower()
    return re.sub(r"\s+", " ", value).strip()


def normalize_rules(config: dict | None = None) -> dict:
    source = config or DEFAULT_RULES
    result = {}
    for key in ("includeKeywords", "excludeKeywords"):
        values = source.get(key, [])
        if not isinstance(values, list):
            raise ValueError(f"{key} phải là danh sách")
        result[key] = list(dict.fromkeys(
            normalized for value in values if (normalized := normalize(str(value)))
        ))[:500]
    result["minimumMatches"] = max(1, min(int(source.get("minimumMatches", 1)), 20))
    result["includeUnmatched"] = bool(source.get("includeUnmatched", True))
    return result


def evaluate(text: str, config: dict | None = None) -> dict:
    normalized = normalize(text)
    rules = normalize_rules(config)
    blocked = [phrase for phrase in rules["excludeKeywords"] if phrase in normalized]
    if blocked:
        return {
            "score": -100,
            "bucket": "blocked",
            "reasons": [f"Nội dung loại trừ: {phrase}" for phrase in blocked],
            "blocked_reason": ", ".join(blocked),
        }

    matches = [phrase for phrase in rules["includeKeywords"] if phrase in normalized]
    score = len(matches)
    reasons = [f"Khớp rule: {phrase}" for phrase in matches[:5]]
    bucket = "candidate" if score >= rules["minimumMatches"] else "uncertain"
    if not reasons:
        reasons.append("Chưa thấy từ khóa rõ; vẫn giữ để tránh bỏ sót")
    return {
        "score": score,
        "bucket": bucket,
        "reasons": reasons,
        "blocked_reason": None,
    }


def draft_comment(text: str) -> str:
    subject = "giải pháp công nghệ phù hợp với nhu cầu này"
    return (
        f"DK-Tech có thể hỗ trợ {subject}. "
        "Bạn có thể inbox để trao đổi yêu cầu cụ thể, hoặc liên hệ 0342391808 ạ."
    )

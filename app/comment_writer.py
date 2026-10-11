"""Local Qwen comment writer for rule-selected Facebook posts."""

from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "qwen3:1.7b"
PHONE = "0342391808"
BLOCKED = ("cờ bạc", "cá cược", "casino", "tài xỉu", "game bài", "đánh bạc", "lô đề", "nhà cái", "data game")

SYSTEM = """Bạn là người viết comment cho Page DK-Tech, chuyên website, phần mềm, tool, bot và tự động hóa cho doanh nghiệp.
Bạn chỉ được viết dựa trên nội dung bài Facebook.
Yêu cầu bắt buộc:
- Viết đúng một comment tiếng Việt tự nhiên, 1-2 câu, từ 60 đến 280 ký tự.
- Nêu đúng dịch vụ phù hợp với nhu cầu cụ thể trong bài; không viết chung chung.
- Chỉ nhắc tính năng hoặc nhu cầu đã xuất hiện trong bài; không tự thêm khả năng mới.
- Xưng DK-Tech; mời inbox hoặc liên hệ 0342391808 đúng một lần.
- Không bịa giá, thời gian, tính năng, kinh nghiệm, cam kết hoặc thông tin chưa có.
- Không nhắc đến AI, thuật toán hay việc tự động hóa comment.
- Không dùng markdown, hashtag, URL hoặc lời chào dài.
- Giọng tự nhiên, ngắn gọn; tránh các cụm quảng cáo sáo rỗng như "chuyên nghiệp", "hàng đầu", "tối ưu cho doanh nghiệp bạn".
- Cấu trúc ưu tiên: "DK-Tech có thể hỗ trợ [đúng nhu cầu]. Bạn inbox hoặc liên hệ 0342391808 để trao đổi thêm nhé."
- Chỉ trả JSON theo schema được cung cấp."""

SCHEMA = {
    "type": "object",
    "properties": {"comment": {"type": "string"}},
    "required": ["comment"],
    "additionalProperties": False,
}


def _request(path: str, payload: dict | None = None, timeout: int = 120) -> dict:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{OLLAMA_URL}{path}", data=body,
        headers={"Content-Type": "application/json"} if body else {},
        method="POST" if body else "GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Không gọi được Ollama/Qwen: {exc}") from exc


def status() -> dict:
    try:
        tags = _request("/api/tags", timeout=3)
        names = {item.get("name") for item in tags.get("models", [])}
        return {"available": True, "model": MODEL, "installed": MODEL in names, "error": None}
    except RuntimeError as exc:
        return {"available": False, "model": MODEL, "installed": False, "error": str(exc)}


def _parse_comment(content: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", content or "", flags=re.DOTALL).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise ValueError("Qwen không trả JSON hợp lệ")
        value = json.loads(match.group(0))
    text = re.sub(r"\s+", " ", str(value.get("comment", ""))).strip().strip('"')
    lowered = text.lower()
    if not 60 <= len(text) <= 280:
        raise ValueError("Comment do Qwen tạo phải dài 60-280 ký tự")
    if "dk-tech" not in lowered or text.count(PHONE) != 1:
        raise ValueError("Comment phải có DK-Tech và đúng một số liên hệ")
    if "http://" in lowered or "https://" in lowered or "#" in text:
        raise ValueError("Comment không được chứa URL hoặc hashtag")
    if any(phrase in lowered for phrase in BLOCKED):
        raise ValueError("Comment chứa nội dung bị chặn")
    return text


def generate(post_text: str) -> dict:
    if not (post_text or "").strip():
        raise ValueError("Bài không có nội dung để sinh comment")
    prompt = json.dumps({
        "facebook_post": post_text[:12000],
        "task": "Viết một comment DK-Tech riêng cho đúng nhu cầu trong bài.",
    }, ensure_ascii=False)
    response = _request("/api/chat", {
        "model": MODEL,
        "stream": False,
        "think": False,
        "format": SCHEMA,
        "keep_alive": "10m",
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0.35, "top_p": 0.8, "num_predict": 160, "repeat_penalty": 1.12},
    })
    comment = _parse_comment(response.get("message", {}).get("content", ""))
    return {
        "comment": comment,
        "model": MODEL,
        "doneReason": response.get("done_reason"),
        "totalDurationNs": response.get("total_duration"),
        "evalCount": response.get("eval_count"),
    }

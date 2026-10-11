"""Extract post bodies from a pasted dashboard, excluding UI labels and comment history."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path


def content_group(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"https?://\S+", " URL ", text)
    text = re.sub(r"\d+", " N ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def extract(source: Path) -> list[dict]:
    raw = source.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    marker = "\nTất cả\nTiềm năng\nChưa chắc\nĐã chặn\n"
    if marker not in raw:
        raise ValueError("Không tìm thấy phần danh sách bài; không lấy lịch sử comment làm dữ liệu học.")
    body = raw.split(marker, 1)[1]
    posts = []
    for block in body.split("\nMở bài\n"):
        block = block.strip()
        if not block:
            continue
        metadata = re.search(r"\n(?:Tiềm năng|Chưa chắc|Đã chặn)\nĐiểm -?\d+\n", block)
        if not metadata:
            raise ValueError("Một khối bài không có ranh giới metadata rõ ràng")
        post_id = re.search(r"^ID (\d+)$", block[metadata.start():], re.M)
        if not post_id:
            raise ValueError("Một khối bài không có ID")
        group, text = block[:metadata.start()].split("\n", 1)
        posts.append({"id": post_id.group(1), "group_name": group.strip(),
                      "text": text.strip(), "content_group": content_group(text),
                      "source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    if len({post["id"] for post in posts}) != len(posts):
        raise ValueError("Trùng ID bài trong nguồn")
    return posts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    posts = extract(args.source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Extracted {len(posts)} posts, {len({p['content_group'] for p in posts})} content groups")

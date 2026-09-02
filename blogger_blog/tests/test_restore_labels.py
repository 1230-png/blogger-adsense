"""라벨 복구 테스트.

add_internal_links.py 의 첫 판이 발행된 12편의 라벨을 지웠다. 이 스크립트는
그 사고를 되돌리기 위한 것이고, 여기서 막고 싶은 사고는 '복구하려다 멀쩡한
라벨까지 카테고리 하나로 덮어쓰는 것'이다.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import restore_labels as rl  # noqa: E402

HOST = "soo-c9.blogspot.com"


def test_카테고리_슬러그를_한글_라벨로_옮긴다(tmp_path, monkeypatch):
    used = tmp_path / "used_topics.json"
    used.write_text(json.dumps([
        {"topic": "a", "category": "finance", "url": f"https://{HOST}/a.html"},
        {"topic": "b", "category": "health", "url": f"https://{HOST}/b.html"},
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(rl, "USED_JSON", used)

    mapping = rl.load_url_labels()
    assert mapping[f"https://{HOST}/a.html"] == "재테크"
    assert mapping[f"https://{HOST}/b.html"] == "건강"


def test_기록_파일이_없으면_빈_매핑(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "USED_JSON", tmp_path / "없음.json")
    assert rl.load_url_labels() == {}


def test_깨진_기록_파일에도_터지지_않는다(tmp_path, monkeypatch):
    broken = tmp_path / "used_topics.json"
    broken.write_text("{{{ 깨진", encoding="utf-8")
    monkeypatch.setattr(rl, "USED_JSON", broken)
    assert rl.load_url_labels() == {}


def test_url이_없는_기록은_건너뛴다(tmp_path, monkeypatch):
    used = tmp_path / "used_topics.json"
    used.write_text(json.dumps([{"topic": "a", "category": "finance"}], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(rl, "USED_JSON", used)
    assert rl.load_url_labels() == {}


def test_복구_본문이_제목과_내용을_유지한다():
    post = {"id": "1", "title": "제목", "content": "<p>본문</p>"}
    body = rl.update_body(post, ["재테크"])
    assert body["title"] == "제목"
    assert body["content"] == "<p>본문</p>"
    assert body["labels"] == ["재테크"]


def test_pick_topic과_같은_카테고리_라벨을_쓴다():
    """라벨 문구가 어긋나면 같은 분류에 라벨이 두 개 생긴다."""
    import pick_topic

    assert rl.CATEGORY_LABELS == pick_topic.CATEGORY_LABELS

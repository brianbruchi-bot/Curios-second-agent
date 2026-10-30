import io
import json
import sys
from urllib.error import HTTPError
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


def sample_video():
    return {
        "title": "File:Red fox in a forest.webm",
        "description": (
            "A red fox walks slowly through a forest during the early morning. "
            "The animal pauses near a fallen tree and looks toward the camera. "
            "Soft light filters through the branches as the fox moves away."
        ),
    }


def test_make_story_uses_complete_sentences():
    title, narration = main.make_story(sample_video())
    assert title == "Red fox in a forest"
    assert narration.startswith("Take a closer look:")
    assert narration.endswith(".")
    assert "Soft light filters" in narration


def test_make_srt_covers_full_duration(tmp_path):
    target = tmp_path / "captions.srt"
    main.make_srt("One two three four five six seven eight.", 8.0, target)
    content = target.read_text(encoding="utf-8")
    assert "00:00:00,000 -->" in content
    assert "00:00:08,000" in content


def test_learning_memory_avoids_duplicate_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "STATE_DIR", tmp_path)
    monkeypatch.setattr(main, "STATE_FILE", tmp_path / "learning.json")
    state = main.load_learning()
    video = {"source_page": "https://example.test/source", "title": "Test source", "search_query": "wildlife"}
    main.remember_success(state, video, "A short narration.", 12.5)
    loaded = main.load_learning()
    assert loaded["successful_runs"] == 1
    assert loaded["query_counts"]["wildlife"] == 1
    assert loaded["seen_sources"] == ["https://example.test/source"]
    assert loaded["source_scores"]["https://example.test/source"]["last_duration_seconds"] == 12.5


def test_learning_state_is_valid_json(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "STATE_DIR", tmp_path)
    monkeypatch.setattr(main, "STATE_FILE", tmp_path / "learning.json")
    state = main.load_learning()
    main.save_learning(state)
    parsed = json.loads((tmp_path / "learning.json").read_text(encoding="utf-8"))
    assert parsed["successful_runs"] == 0


def test_short_source_is_skipped_and_next_candidate_is_used(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(main, "STATE_DIR", tmp_path / ".agent_state")
    monkeypatch.setattr(main, "STATE_FILE", tmp_path / ".agent_state" / "learning.json")
    candidates = [
        {"url": "https://example.test/short.webm", "source_page": "short", "title": "File:Short.webm", "description": sample_video()["description"]},
        {"url": "https://example.test/valid.mp4", "source_page": "valid", "title": "File:Valid.webm", "description": sample_video()["description"]},
    ]

    def fake_find(state):
        return next((item for item in candidates if item["source_page"] not in state["seen_sources"]), None)

    def fake_download(url, destination):
        destination.write_bytes(b"video-data" * 20000)

    monkeypatch.setattr(main, "find_open_video", fake_find)
    monkeypatch.setattr(main, "download_video", fake_download)
    monkeypatch.setattr(main, "duration_seconds", lambda path: 4.0 if path.suffix == ".webm" else 12.0)

    learning = main.load_learning()
    video, path, duration = main.download_suitable_video(learning, attempts=2)
    assert video["source_page"] == "valid"
    assert duration == 12.0
    assert path.exists()


def test_make_story_joins_lowercase_sentence_fragments():
    video = {
        "title": "File:Wildlife center.webm",
        "description": (
            "A broadcast from the Wildlife Center of Texas. "
            "a wildlife rehabilitation center, reaches young patients at the hospital during difficult treatment and recovery."
        ),
    }
    _, narration = main.make_story(video)
    assert "Texas, a wildlife rehabilitation center" in narration


def test_http_retry_handles_wikimedia_rate_limit(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise HTTPError("https://example.test", 429, "Rate limited", {}, None)
        return io.BytesIO(b"ok")

    monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(main.time, "sleep", lambda delay: None)
    response = main.open_with_retries(object(), timeout=1, attempts=2)
    assert response.read() == b"ok"
    assert calls["count"] == 2


def test_media_filter_rejects_failed_imports_and_tiny_files():
    assert not main.media_info_is_usable({"url": "https://example.test/a.webm", "size": 485_000, "length": 0.04})
    assert not main.media_info_is_usable({"url": "https://example.test/a.webm", "size": 2_000_000, "length": 0.04})
    assert main.media_info_is_usable({"url": "https://example.test/a.webm", "size": 2_000_000, "length": 12})

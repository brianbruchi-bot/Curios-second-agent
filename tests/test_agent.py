import json

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
    video = {"source_page": "https://example.test/source", "title": "Test source"}
    main.remember_success(state, video, "A short narration.", 12.5)
    loaded = main.load_learning()
    assert loaded["successful_runs"] == 1
    assert loaded["seen_sources"] == ["https://example.test/source"]
    assert loaded["source_scores"]["https://example.test/source"]["last_duration_seconds"] == 12.5


def test_learning_state_is_valid_json(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "STATE_DIR", tmp_path)
    monkeypatch.setattr(main, "STATE_FILE", tmp_path / "learning.json")
    state = main.load_learning()
    main.save_learning(state)
    parsed = json.loads((tmp_path / "learning.json").read_text(encoding="utf-8"))
    assert parsed["successful_runs"] == 0

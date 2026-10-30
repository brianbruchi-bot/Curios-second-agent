import io
import json
import sys

import pytest
from urllib.error import HTTPError, URLError
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


def test_title_overlay_never_truncates_mid_word():
    title = "Hot Intergalactic Gas Chandra Discovers Rivers Of Gravity"
    lines = main.format_title_overlay(title).splitlines()
    assert len(lines) <= 2
    assert lines[-1].endswith("…")
    assert not lines[-1].endswith("Rivers")


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
            "a wildlife rehabilitation center, reaches young patients at the hospital during difficult treatment and recovery. The program offers comfort and support to families."
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


def test_source_filter_rejects_risky_how_to_metadata():
    assert not main.is_appropriate_source("Wood Chopping", "How to split wood with a chainsaw.")
    assert not main.is_appropriate_source("Lawn mower blade", "A tutorial about cutting.")
    assert main.is_appropriate_source("Red fox in a forest", "A red fox walks through the forest.")


def test_make_story_removes_redundant_brand_and_year_from_title():
    video = sample_video()
    video["title"] = "File:mypubliclandsroadtrip 2016 Wildlife Watching, Cosumnes River Preserve.webm"
    title, _ = main.make_story(video)
    assert title == "Wildlife Watching, Cosumnes River Preserve"


def test_listen_hook_requires_a_standalone_sound_word():
    video = {
        "title": "File:Instrument processing.webm",
        "description": (
            "The instrument is undergoing final flight preparation at the Kennedy Space Center. "
            "Protective covering is added before the equipment moves to the next processing facility. "
            "The team checks each part carefully before transport."
        ),
    }
    _, narration = main.make_story(video)
    assert narration.startswith("Take a closer look:")


def test_long_source_title_uses_a_complete_short_headline():
    video = sample_video()
    video["title"] = (
        'File:Hot Intergalactic Gas- Chandra Discovers "Rivers Of Gravity" '
        "That Define Cosmic Landscape (2002-igm).webm"
    )
    title, _ = main.make_story(video)
    assert title == "Hot Intergalactic Gas"
    assert len(title) <= 52


def test_http_retry_handles_temporary_network_error(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise URLError("temporary connection failure")
        return io.BytesIO(b"ok")

    monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(main.time, "sleep", lambda delay: None)
    response = main.open_with_retries(object(), timeout=1, attempts=2)
    assert response.read() == b"ok"
    assert calls["count"] == 2


def test_reusable_license_allowlist_and_restrictions():
    assert main.is_reusable_license('CC BY 4.0')
    assert main.is_reusable_license('Public domain')
    assert main.is_reusable_license('CC0')
    assert not main.is_reusable_license('CC BY-NC 4.0')
    assert not main.is_reusable_license('CC BY-ND 4.0')
    assert not main.is_reusable_license('All rights reserved')


def test_upload_package_requires_video_and_matching_attribution(tmp_path, monkeypatch):
    import upload_youtube

    video = tmp_path / "short.mp4"
    video.write_bytes(b"x" * 150_000)
    title = tmp_path / "title.txt"
    title.write_text("A useful title", encoding="utf-8")
    description = tmp_path / "description.txt"
    source = "https://commons.wikimedia.org/wiki/File:Example.webm"
    description.write_text(
        f"A short narration.\\n\\nFootage: {source}\\nCreator: Example\\nLicense: Public domain",
        encoding="utf-8",
    )
    attribution = tmp_path / "attribution.json"
    attribution.write_text(json.dumps({
        "source_page": source, "license": "Public domain",
        "creator": "Example", "video_title": "A useful title",
    }), encoding="utf-8")

    monkeypatch.setattr(upload_youtube, "VIDEO", video)
    monkeypatch.setattr(upload_youtube, "TITLE_FILE", title)
    monkeypatch.setattr(upload_youtube, "DESCRIPTION_FILE", description)
    monkeypatch.setattr(upload_youtube, "ATTRIBUTION_FILE", attribution)
    assert "Footage:" in upload_youtube.validate_upload_package()

    description.write_text("Footage: different source\\nLicense: Public domain", encoding="utf-8")
    with pytest.raises(ValueError, match="does not contain the attributed source page"):
        upload_youtube.validate_upload_package()


def test_public_upload_requires_separate_explicit_approval():
    import upload_youtube

    assert upload_youtube.validate_privacy_settings("private", False) == "private"
    assert upload_youtube.validate_privacy_settings("unlisted", False) == "unlisted"
    with pytest.raises(ValueError, match="Public publishing is locked"):
        upload_youtube.validate_privacy_settings("public", False)
    assert upload_youtube.validate_privacy_settings("public", True) == "public"


def test_youtube_oauth_validation_rejects_incomplete_credentials():
    import upload_youtube
    import pytest
    with pytest.raises(ValueError, match='missing required fields'):
        upload_youtube.validate_token_info({'client_id': 'example'})


def test_youtube_oauth_validation_accepts_required_fields():
    import upload_youtube
    token = {'client_id': 'id', 'client_secret': 'secret', 'refresh_token': 'refresh', 'token_uri': 'https://oauth2.googleapis.com/token'}
    assert upload_youtube.validate_token_info(token) is token

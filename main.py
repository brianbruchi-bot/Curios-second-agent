import asyncio
import html
import json
import random
import re
import subprocess
import time
import textwrap
import urllib.parse
import urllib.request
from urllib.error import HTTPError
from pathlib import Path

import edge_tts

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)
STATE_DIR = Path(".agent_state")
STATE_FILE = STATE_DIR / "learning.json"


def load_learning():
    STATE_DIR.mkdir(exist_ok=True)
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("Learning state must be an object")
    except (OSError, ValueError, json.JSONDecodeError):
        state = {"seen_sources": [], "successful_runs": 0, "source_scores": {}}
    state.setdefault("seen_sources", [])
    state.setdefault("successful_runs", 0)
    state.setdefault("source_scores", {})
    return state


def save_learning(state):
    STATE_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def remember_success(state, video, narration, duration):
    source = video["source_page"]
    seen = [item for item in state.get("seen_sources", []) if item != source]
    seen.append(source)
    state["seen_sources"] = seen[-100:]
    state["successful_runs"] = int(state.get("successful_runs", 0)) + 1
    scores = state.setdefault("source_scores", {})
    scores[source] = {
        "title": video["title"],
        "successful_renders": int(scores.get(source, {}).get("successful_renders", 0)) + 1,
        "last_duration_seconds": round(duration, 2),
        "narration_words": len(narration.split()),
    }
    state["last_success_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_learning(state)
API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "CuriosSecondAgent/1.2 (https://github.com/brianbruchi-bot/Curios-second-agent; contact via repository issues)"
VOICE = "en-US-GuyNeural"


def open_with_retries(request, timeout, attempts=5):
    for attempt in range(attempts):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise
            retry_after = exc.headers.get("Retry-After")
            delay = min(30, int(retry_after)) if retry_after and retry_after.isdigit() else min(30, 2 ** (attempt + 1))
            print(f"Source server returned HTTP {exc.code}; retrying in {delay}s.")
            time.sleep(delay)


def api_get(params):
    url = API + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with open_with_retries(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def clean_html(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def is_english_metadata(title, description):
    text = (title + " " + description).lower()
    if not text or not text.isascii():
        return False
    words = set(re.findall(r"[a-z]+", text))
    english_markers = {
        "the", "and", "of", "in", "for", "with", "water", "wildlife",
        "nature", "forest", "river", "ocean", "animal", "animals",
        "science", "energy", "plant", "plants", "video", "this", "from",
        "how", "what", "wild", "bird", "birds", "mountain", "climate",
    }
    foreign_markers = {
        "pour", "avec", "dans", "des", "une", "les", "sur", "est",
        "que", "par", "der", "die", "das", "und", "una", "del",
    }
    return len(words & english_markers) >= 2 and not (words & foreign_markers)


def find_open_video(learning):
    searches = [
        "filemime:video/webm wildlife",
        "filemime:video/mp4 ocean animals",
        "filemime:video/webm forest animals",
        "filemime:video/mp4 space astronomy",
        "filemime:video/webm nature documentary",
        "filemime:video/mp4 underwater",
    ]
    random.shuffle(searches)
    for query in searches:
        data = api_get({
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": query, "gsrnamespace": 6, "gsrlimit": 30,
            "prop": "imageinfo", "iiprop": "url|extmetadata|size|length",
        })
        pages = list(data.get("query", {}).get("pages", {}).values())
        random.shuffle(pages)
        for page in pages:
            info = (page.get("imageinfo") or [{}])[0]
            url = info.get("url", "")
            if not url or info.get("size", 0) > 80 * 1024 * 1024:
                continue
            if info.get("length") and info["length"] < 8:
                continue
            ext = info.get("extmetadata", {})
            license_name = clean_html(ext.get("LicenseShortName", {}).get("value", "See source page"))
            license_url = ext.get("LicenseUrl", {}).get("value", "")
            license_lower = (license_name + " " + license_url).lower()
            if any(term in license_lower for term in (
                "noncommercial", "non-commercial", "no derivatives", "cc by-nd", "cc-by-nd"
            )):
                continue
            # Only use licenses that are straightforward to reuse and attribute.
            license_ok = (
                "public domain" in license_lower
                or "cc0" in license_lower
                or "creative commons attribution 4.0" in license_lower
                or "creative commons attribution 3.0" in license_lower
                or "cc by 4.0" in license_lower
                or "cc-by-4.0" in license_lower
                or "cc by 3.0" in license_lower
                or "cc-by-3.0" in license_lower
            )
            if not license_ok:
                continue
            title = page.get("title", "Wikimedia Commons video")
            description = clean_html(ext.get("ImageDescription", {}).get("value", ""))
            # Reject title-only metadata: it produced generic narration in earlier tests.
            title_lower = title.lower()
            if len(description) < 180 or description.lower().startswith(title_lower):
                continue
            if any(term in title_lower for term in ("video by", "footage of", "youtube", "promotional")):
                continue
            if not is_english_metadata(title, description):
                continue
            # Avoid metadata-only catalog entries and descriptions that are too thin to narrate.
            meaningful_words = re.findall(r"[A-Za-z]{3,}", description)
            if len(meaningful_words) < 32 or len(re.findall(r"[.!?]", description)) < 2:
                continue
            source_page = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
            if source_page in learning.get("seen_sources", []):
                continue
            return {
                "title": title,
                "url": url,
                "source_page": source_page,
                "license": license_name,
                "license_url": license_url,
                "artist": clean_html(ext.get("Artist", {}).get("value", "Creator not listed")),
                "description": description or title,
            }
    return None


def download_video(url, destination):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with open_with_retries(request, timeout=120) as response, open(destination, "wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def probe_value(path, entry):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", entry,
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def duration_seconds(path):
    return float(probe_value(path, "format=duration"))


def validate_render(path, expected_duration):
    if not path.exists() or path.stat().st_size < 100_000:
        raise RuntimeError("Rendered video is missing or unexpectedly small.")
    duration = duration_seconds(path)
    dimensions = probe_value(path, "stream=width,height").splitlines()
    if len(dimensions) < 2 or dimensions[0] != "1080" or dimensions[1] != "1920":
        raise RuntimeError(f"Rendered video must be 1080x1920; got {dimensions}.")
    codecs = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    if "video" not in codecs or "audio" not in codecs:
        raise RuntimeError("Rendered video must contain both video and audio streams.")
    if duration < 8 or duration > 60 or abs(duration - expected_duration) > 1.5:
        raise RuntimeError(f"Unexpected rendered duration: {duration:.2f}s.")
    return duration


def make_story(video):
    raw_title = re.sub(r"^File:", "", video["title"]).rsplit(".", 1)[0]
    raw_title = re.sub(r"\([^)]{0,80}\)", "", raw_title)
    raw_title = raw_title.replace("_", " ").replace("-", " ").strip()
    title = " ".join(raw_title.split())
    title = re.sub(r"\s+", " ", title).strip(" .")
    title = re.sub(r"\b(video|footage|clip)\b", "", title, flags=re.I).strip()
    description = re.sub(r"\s+", " ", video.get("description", "")).strip()
    description = re.sub(r"https?://\S+", "", description).strip(" -.;")
    # The narration is based on the creator's actual description, not invented facts.
    raw_sentences = re.split(r"(?<=[.!?])\s+", description)
    sentences = []
    for sentence in raw_sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if sentences and sentence[0].islower():
            sentences[-1] = sentences[-1].rstrip(".!?") + ", " + sentence
        else:
            sentences.append(sentence[0].upper() + sentence[1:])
    sentences = [sentence for sentence in sentences if len(sentence.split()) >= 7]
    selected_sentences = []
    for sentence in sentences:
        candidate = " ".join(selected_sentences + [sentence])
        if len(candidate.split()) > 46:
            break
        selected_sentences.append(sentence)
    body = " ".join(selected_sentences).strip()
    if len(body.split()) < 20:
        raise RuntimeError("Source description is too short for a complete narration.")
    # Use a hook that stays faithful to the creator's description.
    hook = "Listen closely:" if re.search(r"sound|sing|call|birdsong|song", body, re.I) else "Take a closer look:"
    narration = f"{hook} {body}"
    if not narration.endswith((".", "!", "?")):
        narration += "."
    if len(title) > 52:
        title = " ".join(title.split()[:7])
    return title, narration


def make_srt(text, duration, destination):
    words = text.split()
    groups = [" ".join(words[i:i + 4]) for i in range(0, len(words), 4)]
    total_words = sum(len(group.split()) for group in groups)
    cursor = 0.0
    entries = []
    for group in groups:
        span = duration * len(group.split()) / total_words
        start = cursor
        end = min(duration, cursor + span)
        def stamp(seconds):
            millis = int(round(seconds * 1000))
            hours, millis = divmod(millis, 3600000)
            minutes, millis = divmod(millis, 60000)
            seconds_int, millis = divmod(millis, 1000)
            return f"{hours:02}:{minutes:02}:{seconds_int:02},{millis:03}"
        entries.append(f"{len(entries) + 1}\n{stamp(start)} --> {stamp(end)}\n{group}\n")
        cursor = end
    destination.write_text("\n".join(entries), encoding="utf-8")


async def synthesize_speech(text, destination):
    communicate = edge_tts.Communicate(text, VOICE, rate="+3%", volume="+0%")
    await communicate.save(str(destination))


def download_suitable_video(learning, attempts=8):
    for attempt in range(1, attempts + 1):
        video = find_open_video(learning)
        if not video:
            break
        suffix = Path(urllib.parse.urlparse(video["url"]).path).suffix or ".video"
        source_path = OUTPUT_DIR / ("source" + suffix)
        try:
            print(f"Candidate {attempt}/{attempts}:", video["title"])
            download_video(video["url"], source_path)
            if source_path.stat().st_size < 100_000:
                print("Skipping suspiciously small media download:", video["title"])
                duration = 0.0
            else:
                duration = duration_seconds(source_path)
            if duration >= 8:
                try:
                    make_story(video)
                except RuntimeError as exc:
                    print("Skipping source with unusable narration metadata:", exc)
                else:
                    return video, source_path, duration
            else:
                print(f"Skipping short source ({duration:.2f}s):", video["title"])
        except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
            print("Skipping source that could not be validated:", exc)
        if video["source_page"] not in learning["seen_sources"]:
            learning["seen_sources"].append(video["source_page"])
            learning["seen_sources"] = learning["seen_sources"][-100:]
            save_learning(learning)
        source_path.unlink(missing_ok=True)
    raise RuntimeError(f"No valid source video of at least 8 seconds found after {attempts} attempts.")


def main():
    print("CURIOS SECOND AGENT — finding openly licensed footage")
    learning = load_learning()
    print("Learning memory:", learning.get("successful_runs", 0), "successful previous renders")
    video, source_path, total = download_suitable_video(learning)
    voice_path = OUTPUT_DIR / "narration.mp3"
    output_path = OUTPUT_DIR / "curios_short.mp4"
    title_path = OUTPUT_DIR / "title.txt"
    captions_path = OUTPUT_DIR / "captions.srt"

    print("Selected validated source:", video["title"])
    clip_duration = min(30.0, total)
    start = random.uniform(0, max(0, total - clip_duration)) if total > clip_duration else 0

    title, narration = make_story(video)
    title_path.write_text("\n".join(textwrap.wrap(title, width=25)[:2]), encoding="utf-8")
    asyncio.run(synthesize_speech(narration, voice_path))
    voice_duration = duration_seconds(voice_path)
    render_duration = min(clip_duration, voice_duration)
    make_srt(narration, render_duration, captions_path)
    if not captions_path.exists() or captions_path.stat().st_size == 0:
        raise RuntimeError("Subtitle file was not created.")

    has_audio = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(source_path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip() == "audio"
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    title_file = str(title_path.resolve()).replace(":", "\\:")
    captions_file = "output/captions.srt"
    video_filter = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        f"drawtext=fontfile={font}:textfile={title_file}:fontcolor=white:fontsize=42:"
        "borderw=3:bordercolor=black:x=(w-text_w)/2:y=90:box=1:boxcolor=black@0.45:boxborderw=16,"
        f"subtitles=filename={captions_file}:force_style='FontName=DejaVu Sans,FontSize=8,"
        "Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=1,"
        "Shadow=0,Alignment=2,MarginV=115'[v]"
    )
    command = [
        "ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", str(source_path),
        "-i", str(voice_path), "-t", f"{render_duration:.2f}",
    ]
    if has_audio:
        audio_filter = (
            "[0:a]volume=0.12[bg_a];[1:a]volume=1.0[voice];"
            "[bg_a][voice]amix=inputs=2:duration=longest:dropout_transition=2[aout]"
        )
    else:
        audio_filter = "[1:a]anull[aout]"
    command += [
        "-filter_complex", video_filter + ";" + audio_filter,
        "-map", "[v]", "-map", "[aout]",
    ]
    command += [
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
        "-pix_fmt", "yuv420p", str(output_path),
    ]
    subprocess.run(command, check=True)
    final_duration = validate_render(output_path, render_duration)
    print(f"QUALITY CHECK PASSED: 1080x1920, audio+video, {final_duration:.2f}s")

    attribution = {
        "source_title": video["title"], "source_page": video["source_page"],
        "creator": video["artist"], "license": video["license"],
        "license_url": video["license_url"], "description": video["description"],
        "clip_start_seconds": round(start, 2), "clip_duration_seconds": round(render_duration, 2),
        "video_title": title, "narration": narration, "voice": VOICE,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "Source license was filtered to public domain, CC0, or CC BY 3.0/4.0. Attribution is included in description.txt.",
    }
    (OUTPUT_DIR / "attribution.json").write_text(
        json.dumps(attribution, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    description = (
        f"{title}\n\n{narration}\n\n"
        f"Footage: {video['source_page']}\nCreator: {video['artist']}\n"
        f"License: {video['license']} {video['license_url']}\n"
        "#shorts #curiosity #nature"
    )
    (OUTPUT_DIR / "description.txt").write_text(description, encoding="utf-8")
    source_path.unlink(missing_ok=True)
    voice_path.unlink(missing_ok=True)
    remember_success(learning, video, narration, render_duration)
    print("LEARNING: remembered source and render quality; total successful renders:", learning["successful_runs"])
    print("SUCCESS: Created narrated, captioned output/curios_short.mp4")
    print("Metadata saved in output/attribution.json and output/description.txt")


if __name__ == "__main__":
    main()

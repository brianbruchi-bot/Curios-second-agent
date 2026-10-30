import asyncio
import html
import json
import random
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

import edge_tts

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)
API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "CuriosSecondAgent/1.1 (automated short creation)"
VOICE = "en-US-GuyNeural"


def api_get(params):
    url = API + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def clean_html(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\\s+", " ", html.unescape(value)).strip()


def find_open_video():
    searches = [
        "filemime:video/webm nature",
        "filemime:video/mp4 wildlife",
        "filemime:video/webm science",
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
            title = page.get("title", "Wikimedia Commons video")
            source_page = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
            return {
                "title": title,
                "url": url,
                "source_page": source_page,
                "license": license_name,
                "license_url": license_url,
                "artist": clean_html(ext.get("Artist", {}).get("value", "Creator not listed")),
                "description": clean_html(ext.get("ImageDescription", {}).get("value", title)),
            }
    return None


def download_video(url, destination):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, open(destination, "wb") as out:
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


def make_story(video):
    source_text = (video["title"] + " " + video["description"]).lower()
    if any(word in source_text for word in ("moss", "forest", "tree", "plant", "flower", "nature")):
        title = "The Hidden World of Nature"
        narration = (
            "Here is something amazing about the natural world. "
            "Moss has no true roots. It absorbs water and nutrients directly across its tiny leaves. "
            "That helps it thrive on rocks, tree trunks, and damp ground. "
            "Small as it looks, moss can create shelter and hold moisture for an entire miniature ecosystem. "
            "Nature is full of quiet wonders."
        )
    elif any(word in source_text for word in ("bird", "animal", "wildlife", "fish", "insect")):
        title = "Wildlife Is More Amazing Than You Think"
        narration = (
            "The natural world is full of surprising adaptations. "
            "Animals survive by using senses, movement, and behaviors shaped over millions of years. "
            "Even a quiet moment in the wild can reveal how carefully life adapts to its surroundings. "
            "Look closer. There is usually more happening than we first notice."
        )
    elif "space" in source_text or "planet" in source_text:
        title = "A Universe Full of Wonders"
        narration = (
            "Space is bigger and stranger than most of us can imagine. "
            "The light reaching your eyes from distant stars began its journey years, centuries, or even longer ago. "
            "When you look into the night sky, you are also looking back in time. "
            "The universe is full of stories still waiting to be discovered."
        )
    else:
        title = "One Small Wonder of Science"
        narration = (
            "Science reminds us that ordinary things can hide extraordinary ideas. "
            "The world around us is shaped by patterns, forces, and processes that are easy to overlook. "
            "Taking a closer look can turn a familiar scene into a fascinating discovery. "
            "Stay curious. There is always more to learn."
        )
    return title, narration


def make_srt(text, duration, destination):
    words = text.split()
    groups = [" ".join(words[i:i + 7]) for i in range(0, len(words), 7)]
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
        entries.append(f"{len(entries) + 1}\\n{stamp(start)} --> {stamp(end)}\\n{group}\\n")
        cursor = end
    destination.write_text("\\n".join(entries), encoding="utf-8")


async def synthesize_speech(text, destination):
    communicate = edge_tts.Communicate(text, VOICE, rate="+3%", volume="+0%")
    await communicate.save(str(destination))


def main():
    print("CURIOS SECOND AGENT — finding openly licensed footage")
    video = find_open_video()
    if not video:
        raise RuntimeError("No suitable openly licensed video found.")

    suffix = Path(urllib.parse.urlparse(video["url"]).path).suffix or ".video"
    source_path = OUTPUT_DIR / ("source" + suffix)
    voice_path = OUTPUT_DIR / "narration.mp3"
    output_path = OUTPUT_DIR / "curios_short.mp4"
    title_path = OUTPUT_DIR / "title.txt"
    captions_path = OUTPUT_DIR / "captions.srt"

    print("Selected:", video["title"])
    download_video(video["url"], source_path)
    total = duration_seconds(source_path)
    clip_duration = min(30.0, total)
    if clip_duration < 8:
        raise RuntimeError("Source video is too short.")
    start = random.uniform(0, max(0, total - clip_duration)) if total > clip_duration else 0

    title, narration = make_story(video)
    title_path.write_text(title, encoding="utf-8")
    asyncio.run(synthesize_speech(narration, voice_path))
    voice_duration = duration_seconds(voice_path)
    make_srt(narration, min(clip_duration, voice_duration), captions_path)

    has_audio = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(source_path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip() == "audio"
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    video_filter = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        f"drawtext=fontfile={font}:textfile={title_path}:fontcolor=white:fontsize=54:"
        "borderw=3:bordercolor=black:x=(w-text_w)/2:y=105:box=1:boxcolor=black@0.35:boxborderw=18,"
        f"subtitles={captions_path}:force_style='FontName=DejaVu Sans,FontSize=17,"
        "Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,"
        "Shadow=1,Alignment=2,MarginV=150'"
    )
    command = [
        "ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", str(source_path),
        "-i", str(voice_path), "-t", f"{clip_duration:.2f}",
        "-vf", video_filter,
    ]
    if has_audio:
        command += [
            "-filter_complex", "[0:a]volume=0.12[bg];[1:a]volume=1.0[voice];[bg][voice]amix=inputs=2:duration=longest:dropout_transition=2[aout]",
            "-map", "0:v:0", "-map", "[aout]",
        ]
    else:
        command += ["-map", "0:v:0", "-map", "1:a:0"]
    command += [
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
        "-pix_fmt", "yuv420p", str(output_path),
    ]
    subprocess.run(command, check=True)

    attribution = {
        "source_title": video["title"], "source_page": video["source_page"],
        "creator": video["artist"], "license": video["license"],
        "license_url": video["license_url"], "description": video["description"],
        "clip_start_seconds": round(start, 2), "clip_duration_seconds": round(clip_duration, 2),
        "video_title": title, "narration": narration, "voice": VOICE,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "Draft created automatically. Verify source license and attribution before publishing.",
    }
    (OUTPUT_DIR / "attribution.json").write_text(
        json.dumps(attribution, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    description = (
        f"{title}\\n\\n{narration}\\n\\n"
        f"Footage: {video['source_page']}\\nCreator: {video['artist']}\\n"
        f"License: {video['license']} {video['license_url']}\\n"
        "#shorts #curiosity #nature"
    )
    (OUTPUT_DIR / "description.txt").write_text(description, encoding="utf-8")
    source_path.unlink(missing_ok=True)
    voice_path.unlink(missing_ok=True)
    print("SUCCESS: Created narrated, captioned output/curios_short.mp4")
    print("Metadata saved in output/attribution.json and output/description.txt")


if __name__ == "__main__":
    main()

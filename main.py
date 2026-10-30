import json
import random
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)
API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "CuriosSecondAgent/1.0 (automated short creation)"


def api_get(params):
    url = API + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def find_open_video():
    searches = ["filemime:video/webm nature", "filemime:video/mp4 wildlife", "filemime:video/webm science"]
    random.shuffle(searches)
    for query in searches:
        data = api_get({
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": query, "gsrnamespace": 6, "gsrlimit": 20,
            "prop": "imageinfo", "iiprop": "url|extmetadata|size|length"
        })
        pages = list(data.get("query", {}).get("pages", {}).values())
        random.shuffle(pages)
        for page in pages:
            info = (page.get("imageinfo") or [{}])[0]
            url = info.get("url", "")
            if not url or info.get("size", 0) > 80 * 1024 * 1024 or (info.get("length") and info.get("length") < 5):
                continue
            ext = info.get("extmetadata", {})
            license_name = ext.get("LicenseShortName", {}).get("value", "See source page")
            license_url = ext.get("LicenseUrl", {}).get("value", "")
            artist = ext.get("Artist", {}).get("value", "Creator not listed")
            description = ext.get("ImageDescription", {}).get("value", page.get("title", ""))
            title = page.get("title", "Wikimedia Commons video")
            source_page = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
            license_lower = (license_name + " " + license_url).lower()
            if "noncommercial" in license_lower or "non-commercial" in license_lower or "no derivatives" in license_lower or "nd" in license_lower:
                continue
            return {"title": title, "url": url, "source_page": source_page,
                    "license": license_name, "license_url": license_url,
                    "artist": artist, "description": description}
    return None


def download_video(url, destination):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=90) as response, open(destination, "wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def duration_seconds(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True
    )
    return float(result.stdout.strip())


def main():
    print("CURIOS SECOND AGENT — searching Wikimedia Commons for an openly licensed video")
    video = find_open_video()
    if not video:
        raise RuntimeError("No suitable video found in Wikimedia Commons search.")

    suffix = Path(urllib.parse.urlparse(video["url"]).path).suffix or ".video"
    source_path = OUTPUT_DIR / ("source" + suffix)
    output_path = OUTPUT_DIR / "curios_short.mp4"
    print("Selected:", video["title"])
    download_video(video["url"], source_path)

    total = duration_seconds(source_path)
    clip_duration = min(30.0, total)
    start = random.uniform(0, max(0, total - clip_duration)) if total > clip_duration else 0
    if clip_duration < 5:
        raise RuntimeError("Source video is too short to make a useful Short.")

    command = [
        "ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", str(source_path),
        "-t", f"{clip_duration:.2f}",
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        "-pix_fmt", "yuv420p", str(output_path)
    ]
    subprocess.run(command, check=True)

    attribution = {
        "source_title": video["title"], "source_page": video["source_page"],
        "creator": video["artist"], "license": video["license"],
        "license_url": video["license_url"], "description": video["description"],
        "clip_start_seconds": round(start, 2), "clip_duration_seconds": round(clip_duration, 2),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "Review the source page and license terms before publishing. This agent creates a draft; it does not upload to YouTube."
    }
    (OUTPUT_DIR / "attribution.json").write_text(json.dumps(attribution, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "description.txt").write_text(
        f"{video['title']}\n\nSource: {video['source_page']}\nCreator: {video['artist']}\n"
        f"License: {video['license']} {video['license_url']}\n", encoding="utf-8"
    )
    source_path.unlink(missing_ok=True)
    print("SUCCESS: Created output/curios_short.mp4")
    print("Attribution saved in output/attribution.json and output/description.txt")


if __name__ == "__main__":
    main()

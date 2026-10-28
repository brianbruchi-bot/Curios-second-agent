import os
import subprocess
from pathlib import Path

# Curios Second Agent
# YouTube Shorts automation starter

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

def check_tools():
    """Check whether the required video tools are installed."""
    for tool in ["ffmpeg", "yt-dlp"]:
        try:
            subprocess.run(
                [tool, "--version"],
                capture_output=True,
                check=True
            )
            print(f"OK: {tool} is installed")
        except (FileNotFoundError, subprocess.CalledProcessError):
            print(f"WARNING: {tool} is not installed")

def create_short(video_path, start_time=0, duration=30):
    """Create a vertical 30-second YouTube Short from an authorized video."""
    video_path = Path(video_path)

    if not video_path.exists():
        print(f"Video not found: {video_path}")
        return False

    output_path = OUTPUT_DIR / "short.mp4"

    command = [
        "ffmpeg",
        "-y",
        "-ss", str(start_time),
        "-i", str(video_path),
        "-t", str(duration),
        "-vf",
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-movflags", "+faststart",
        str(output_path)
    ]

    try:
        subprocess.run(command, check=True)
        print(f"Short created: {output_path}")
        return True
    except subprocess.CalledProcessError as error:
        print(f"Video processing failed: {error}")
        return False

def main():
    print("================================")
    print(" CURIOS SECOND AGENT")
    print(" YouTube Shorts Automation")
    print("================================")

    check_tools()

    source_video = os.getenv("SOURCE_VIDEO", "")

    if source_video:
        create_short(source_video)
    else:
        print("Waiting for an authorized source video.")
        print("The agent is ready for the next setup step.")

if __name__ == "__main__":
    main()

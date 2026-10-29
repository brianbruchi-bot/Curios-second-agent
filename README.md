https://github.com/brianbruchi-bot/Curios-second-agent
import argparse
import subprocess
import shutil
from pathlib import Path


def create_clips(video_path, clip_seconds=30):
    video = Path(video_path)

    if not video.exists():
        print(f"Error: video not found: {video}")
        return

    if not shutil.which("ffmpeg"):
        print("Error: FFmpeg is not installed.")
        return

    output_dir = Path("clips")
    output_dir.mkdir(exist_ok=True)

    duration_result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video)
        ],
        capture_output=True,
        text=True
    )

    if duration_result.returncode != 0:
        print("Could not read video duration.")
        return

    duration = float(duration_result.stdout.strip())
    start = 0
    clip_number = 1

    while start < duration:
        output_file = output_dir / f"clip_{clip_number:03}.mp4"

        command = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(video),
            "-t", str(clip_seconds),
            "-vf",
            "scale
name: Curios Second Agent

on:
  workflow_dispatch:

jobs:
  run-agent:
    runs-on: ubuntu-latest

    steps:
      - name: Get project
        uses: actions/checkout@v4

      - name: Install Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install FFmpeg
        run: |
          sudo apt-get update
          sudo apt-get install -y ffmpeg

      - name: Run agent
        run: python main.py

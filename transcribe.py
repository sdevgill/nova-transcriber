"""
Batch transcriber for Deepgram SDK v3 with Nova 3
=================================================

Examples
--------
# Chunk of 5 files, 6 parallel uploads
python transcribe.py /path/to/audio --output-dir /path/to/text --batch 5 --concurrency 6

# Next 30 with Rich progress bar
python transcribe.py /path/to/audio --output-dir /path/to/text --batch 30 --concurrency 6 --progress rich

# Transcribe everything else with defaults
python transcribe.py /path/to/audio --output-dir /path/to/text
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Protocol

import httpx
from dotenv import load_dotenv
from deepgram import DeepgramClient, PrerecordedOptions, FileSource
from tqdm import tqdm

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".webm"}

# USD per audio minute for Nova‑3 pre‑recorded (pay‑as‑you‑go).
# Override with DG_RATE_PER_MIN in .env if pricing changes.
DEFAULT_RATE = 0.0043

# Max characters of file name to show in per‑file log line
NAME_WIDTH = 55


# --------------------------------------------------------------------------- #
# Progress bar
# --------------------------------------------------------------------------- #
class Bar(Protocol):
    def update(self, n: int = 1) -> None: ...
    def write(self, msg: str) -> None: ...


class TqdmBar:
    def __init__(self, total: int):
        self._bar = tqdm(total=total, desc="Transcribing")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._bar.close()

    def update(self, n: int = 1) -> None:
        self._bar.update(n)

    def write(self, msg: str) -> None:
        self._bar.write(msg)


class RichBar:
    def __init__(self, total: int):
        from rich.progress import Progress, SpinnerColumn, BarColumn, TimeElapsedColumn

        self._prog = Progress(
            SpinnerColumn(),
            "[progress.description]{task.description}",
            BarColumn(),
            TimeElapsedColumn(),
            transient=True,
        )
        self._task = self._prog.add_task("Transcribing", total=total)

    def __enter__(self):  # noqa: D401
        self._prog.__enter__()
        return self

    def __exit__(self, *exc):
        self._prog.__exit__(*exc)

    def update(self, n: int = 1) -> None:
        self._prog.update(self._task, advance=n)

    def write(self, msg: str) -> None:
        self._prog.console.print(msg)


def make_bar(style: str, total: int) -> Bar:
    return RichBar(total) if style == "rich" else TqdmBar(total)


# --------------------------------------------------------------------------- #
# Deepgram helpers
# --------------------------------------------------------------------------- #
def dg_client() -> DeepgramClient:
    load_dotenv()
    key = os.getenv("DEEPGRAM_API_KEY")
    if not key:
        sys.exit("DEEPGRAM_API_KEY missing – add it to a .env file")
    return DeepgramClient(key)


async def transcribe_one(
    client: DeepgramClient, path: Path, timeout: float
) -> tuple[str, float]:
    """Return (transcript, audio_duration_seconds)."""
    with path.open("rb") as f:
        payload: FileSource = {"buffer": f.read()}

    opts = PrerecordedOptions(model="nova-3", smart_format=True)
    resp = await client.listen.asyncrest.v("1").transcribe_file(
        payload, opts, timeout=httpx.Timeout(timeout, connect=10)
    )
    data = json.loads(resp.to_json())
    transcript = data["results"]["channels"][0]["alternatives"][0]["transcript"]
    duration = data.get("metadata", {}).get("duration", 0.0)  # seconds
    return transcript, float(duration)


async def worker(
    sem: asyncio.Semaphore,
    client: DeepgramClient,
    src: Path,
    dst: Path,
    timeout: float,
    bar: Bar,
    rate_per_min: float,
) -> Tuple[float, float, float]:
    """Process one file, return (elapsed_wall_time, audio_secs, cost_usd)."""
    async with sem:
        wall_start = time.perf_counter()
        audio_secs = cost = 0.0
        try:
            transcript, audio_secs = await transcribe_one(client, src, timeout)
            dst.write_text(transcript, encoding="utf-8")
            cost = (audio_secs / 60) * rate_per_min
            elapsed = time.perf_counter() - wall_start

            name = src.name
            name_display = (
                (name[: NAME_WIDTH - 1] + "…") if len(name) > NAME_WIDTH else name
            )
            name_display = name_display.ljust(NAME_WIDTH)

            bar.write(
                f"✔︎ {name_display} | "
                f"{audio_secs/60:6.2f} min | "
                f"{elapsed:6.1f} s | "
                f"${cost:7.4f}"
            )
        except Exception as e:
            bar.write(f"[ERROR] {src.name}: {e}")
        finally:
            bar.update(1)
            return time.perf_counter() - wall_start, audio_secs, cost


async def run(
    input_dir: Path,
    output_dir: Path,
    batch: int,
    concurrency: int,
    timeout: float,
    progress: str,
) -> None:
    client = dg_client()
    rate_per_min = float(os.getenv("DG_RATE_PER_MIN", DEFAULT_RATE))
    output_dir.mkdir(parents=True, exist_ok=True)

    queue: list[tuple[Path, Path]] = []
    for f in sorted(input_dir.iterdir()):
        if f.suffix.lower() not in AUDIO_EXTS:
            continue
        target = output_dir / f.with_suffix(".txt").name
        if not target.exists():
            queue.append((f, target))
        if len(queue) >= batch:
            break

    if not queue:
        print("Nothing to do – already transcribed or nothing found.")
        return

    sem = asyncio.Semaphore(concurrency)
    with make_bar(progress, len(queue)) as bar:
        tasks = [
            asyncio.create_task(
                worker(sem, client, src, dst, timeout, bar, rate_per_min)
            )
            for src, dst in queue
        ]
        results = await asyncio.gather(*tasks)

    total_elapsed = sum(r[0] for r in results)
    total_audio = sum(r[1] for r in results)
    total_cost = sum(r[2] for r in results)

    print(
        f"\n"
        f"\nProcessed {len(queue)} files | "
        f"{total_audio/60:.2f} min audio | "
        f"elapsed {total_elapsed:.1f}s | "
        f"cost ${total_cost:.4f}"
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    p = argparse.ArgumentParser("Deepgram batch transcriber")
    p.add_argument("input_dir", type=Path, help="Folder of audio files")
    p.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Where .txt transcripts go",
    )
    p.add_argument("--batch", type=int, default=50, help="Files per run")
    p.add_argument("--concurrency", type=int, default=4, help="Parallel uploads")
    p.add_argument("--timeout", type=float, default=300, help="HTTP timeout per file")
    p.add_argument(
        "--progress",
        choices=["tqdm", "rich"],
        default="tqdm",
        help="Progress bar type",
    )
    args = p.parse_args()

    if not args.input_dir.is_dir():
        p.error(f"{args.input_dir} is not a directory")

    asyncio.run(
        run(
            args.input_dir,
            args.output_dir,
            args.batch,
            args.concurrency,
            args.timeout,
            args.progress,
        )
    )


if __name__ == "__main__":
    main()

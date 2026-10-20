"""Generate one Friday newsletter from the editor's saved approvals."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import json
from datetime import date, datetime
import sys

from newsletter_approval import load_approval
from project_paths import AUDIO_GENERATED_DIR, AUTOMATION_STATE_PATH, LOG_DIR

OUTPUT_DIR = AUDIO_GENERATED_DIR
LOG_PATH = LOG_DIR / "friday_newsletter.log"


def automation_is_enabled():
    if not AUTOMATION_STATE_PATH.exists():
        return False
    try:
        with AUTOMATION_STATE_PATH.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return isinstance(payload, dict) and payload.get("enabled") is True
    except (OSError, json.JSONDecodeError):
        return False


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--for-date",
        type=date.fromisoformat,
        default=date.today(),
        help="Friday edition date in YYYY-MM-DD format (defaults to the computer's local date).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    issue_date = args.for_date
    if issue_date.weekday() != 4:
        print(f"Refusing to run: {issue_date.isoformat()} is not a Friday edition date.")
        return 1

    if not automation_is_enabled():
        print("Friday automation is disabled in the dashboard. No audio was generated.")
        return 0

    try:
        rows, script = load_approval(issue_date)
    except RuntimeError as exc:
        print(f"Approval check failed: {exc}")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    mp3_target = OUTPUT_DIR / f"icir_newsletter_{issue_date:%Y%m%d}.mp3"
    if mp3_target.is_file() and mp3_target.stat().st_size > 0:
        print(f"Audio for {issue_date.isoformat()} already exists; skipping to avoid duplicate generation: {mp3_target}")
        return 0

    timestamp = datetime.now().isoformat(timespec="seconds")
    try:
        from newsletter_audio import generate_newsletter_audio

        generate_newsletter_audio(script, filename=str(mp3_target))
        print(f"Newsletter audio generated for {issue_date.isoformat()} from {len(rows)} approved stories: {mp3_target}")
        print(f"Generated at {timestamp}. This job creates audio only; it does not send or publish it.")
        return 0
    except Exception as exc:
        print(f"Newsletter audio generation failed: {exc}")
        return 1


if __name__ == "__main__":
    class Tee:
        def __init__(self, *streams):
            self.streams = streams

        def write(self, message):
            for stream in self.streams:
                stream.write(message)
                stream.flush()
            return len(message)

        def flush(self):
            for stream in self.streams:
                stream.flush()

    LOG_PATH.parent.mkdir(exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(f"\n--- Started {datetime.now().astimezone().isoformat(timespec='seconds')} ---\n")
        log_file.flush()
        stdout = Tee(sys.stdout, log_file)
        stderr = Tee(sys.stderr, log_file)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            raise SystemExit(main())

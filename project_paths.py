"""Shared paths for local configuration, newsletter state, and audio files."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent

CONFIG_DIR = ROOT / "config"
ENV_FILE = CONFIG_DIR / ".env"

NEWSLETTER_DIR = ROOT / "newsletter"
STORIES_PATH = NEWSLETTER_DIR / "stories.json"
STORIES_CSV_PATH = NEWSLETTER_DIR / "stories.csv"
FINAL_SCRIPT_PATH = NEWSLETTER_DIR / "newsletter_script.txt"
REVIEW_PATH = NEWSLETTER_DIR / "newsletter_review.csv"
APPROVAL_PATH = NEWSLETTER_DIR / "newsletter_approval.json"
AUTOMATION_STATE_PATH = NEWSLETTER_DIR / "automation_state.json"

AUDIO_DIR = ROOT / "audio"
AUDIO_SAMPLES_DIR = AUDIO_DIR / "samples"
AUDIO_GENERATED_DIR = AUDIO_DIR / "generated"

LOG_DIR = ROOT / "logs"


def ensure_project_dirs():
    for directory in (CONFIG_DIR, NEWSLETTER_DIR, AUDIO_SAMPLES_DIR, AUDIO_GENERATED_DIR):
        directory.mkdir(parents=True, exist_ok=True)

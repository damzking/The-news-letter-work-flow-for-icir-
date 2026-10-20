import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from project_paths import AUDIO_GENERATED_DIR, ENV_FILE, FINAL_SCRIPT_PATH

load_dotenv(ENV_FILE, override=True)

API_BASE = "https://api.kittenml.com/v1"


def generate_with_kittenml(script, filename, api_key, voice_id):
    if not api_key:
        raise RuntimeError("KittenML is selected, but KITTENML_API_KEY is not configured.")
    if not voice_id:
        raise RuntimeError("KittenML is selected, but KITTENML_VOICE_ID is not configured. Register your sample voice first.")
    response = requests.post(
        f"{API_BASE}/audio/speech",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "kitten-tts-2-latest",
            "voice": {"id": voice_id},
            "input": script,
            "response_format": "mp3",
        },
        timeout=180,
    )
    if not response.ok:
        raise RuntimeError(
            f"KittenML returned HTTP {response.status_code}. Check the configured key, account access, and quota."
        )
    Path(filename).write_bytes(response.content)
    print(f"Saved KittenML audio using voice {voice_id} to {filename}")
    return filename


def generate_with_elevenlabs(script, filename, voice_id):
    from elevenlabs.client import ElevenLabs

    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key or not api_key.startswith("sk_"):
        raise RuntimeError("ELEVENLABS_API_KEY is missing or invalid.")
    client = ElevenLabs(api_key=api_key)

    def attempt(selected_voice):
        stream = client.text_to_speech.convert(
            voice_id=selected_voice,
            text=script,
            model_id="eleven_multilingual_v2",
            output_format="mp3_22050_32",
        )
        return b"".join(chunk for chunk in stream if chunk)

    try:
        audio = attempt(voice_id)
        used_voice = voice_id
    except Exception:
        print("Selected ElevenLabs voice failed; trying fallback voices.")
        audio = b""
        used_voice = None
        for fallback_voice in ("EXAVITQu4vr4xnSDxMaL", "JBFqnCBsd6RMkjVDRZzb", "pNInz6obpgDQGcFmaJgB"):
            if fallback_voice == voice_id:
                continue
            try:
                audio = attempt(fallback_voice)
                used_voice = fallback_voice
                break
            except Exception:
                print("An ElevenLabs fallback voice failed.")
    if not audio:
        raise RuntimeError("Audio generation failed for the selected and fallback ElevenLabs voices.")
    Path(filename).write_bytes(audio)
    print(f"Saved audio using ElevenLabs voice {used_voice} to {filename}")
    return filename


def generate_newsletter_audio(
    script,
    filename=str(AUDIO_GENERATED_DIR / "daily_newsletter.mp3"),
    voice_id=None,
    provider=None,
    api_key=None,
):
    selected_provider = (provider or os.getenv("TTS_PROVIDER", "elevenlabs")).strip().lower()
    if selected_provider == "kittenml":
        return generate_with_kittenml(
            script,
            filename,
            api_key or os.getenv("KITTENML_API_KEY"),
            voice_id or os.getenv("KITTENML_VOICE_ID"),
        )
    if selected_provider == "elevenlabs":
        return generate_with_elevenlabs(
            script,
            filename,
            voice_id or os.getenv("ELEVENLABS_VOICE_ID", "v411uyEKbaj63pTJHHbK"),
        )
    raise ValueError("TTS_PROVIDER must be either 'kittenml' or 'elevenlabs'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the ICIR newsletter audio file.")
    parser.add_argument(
        "--output",
        default=str(AUDIO_GENERATED_DIR / "daily_newsletter.mp3"),
        help="MP3 output path (defaults to daily_newsletter.mp3).",
    )
    args = parser.parse_args()
    script_file = FINAL_SCRIPT_PATH
    script = script_file.read_text(encoding="utf-8") if script_file.exists() else "Good morning, welcome to today's ICIR briefing."
    print("Generating newsletter audio...")
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    try:
        result = generate_newsletter_audio(script, filename=args.output)
    except RuntimeError as exc:
        print(f"Audio generation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as exc:
        print(f"Audio generation failed ({type(exc).__name__}).", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"Done! Saved to {result}")

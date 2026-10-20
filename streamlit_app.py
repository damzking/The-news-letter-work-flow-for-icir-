import json
import hashlib
import os
import subprocess
import sys
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from newsletter_approval import save_approval
from project_paths import (
    AUTOMATION_STATE_PATH,
    AUDIO_GENERATED_DIR,
    ENV_FILE,
    FINAL_SCRIPT_PATH,
    ROOT,
    STORIES_CSV_PATH,
    STORIES_PATH,
    ensure_project_dirs,
)
from scrape_icir import clean_story_text, get_article_text, summarize_story, trim_newsletter_summary


ensure_project_dirs()
load_dotenv(ENV_FILE, override=True)

try:
    for secret_name in ("GOOGLE_API_KEY", "OPENAI_API_KEY", "TTS_PROVIDER"):
        secret_value = st.secrets.get(secret_name, "")
        if secret_value:
            os.environ[secret_name] = str(secret_value)
except Exception:
    pass


def load_automation_state():
    if not AUTOMATION_STATE_PATH.exists():
        return {"enabled": False}
    try:
        with AUTOMATION_STATE_PATH.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            return {"enabled": False}
        return {"enabled": bool(payload.get("enabled", False))}
    except Exception:
        return {"enabled": False}


def save_automation_state(enabled):
    payload = {"enabled": bool(enabled)}
    with AUTOMATION_STATE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return payload


@st.cache_data
def load_stories():
    if not STORIES_PATH.exists():
        return pd.DataFrame(columns=["select", "title", "category", "url", "summary"])

    with STORIES_PATH.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    stories = payload.get("stories", [])
    rows = []
    for index, story in enumerate(stories, start=1):
        summary_text = (
            story.get("summary")
            or story.get("text")
            or story.get("title")
            or ""
        )
        summary_value = trim_newsletter_summary(summary_text)
        rows.append(
            {
                "select": False,
                "order": index,
                "title": story.get("title", ""),
                "category": story.get("category", "General"),
                "url": story.get("url", ""),
                "summary": str(summary_value),
            }
        )
    return pd.DataFrame(rows)


def refresh_stories():
    cmd = [sys.executable, str(ROOT / "scrape_icir.py"), "--source", "feed", "--limit", "10", "--full", "--out", str(STORIES_PATH), "--csv", str(STORIES_CSV_PATH)]
    completed = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if completed.returncode != 0:
        detail = (completed.stdout or "") + (completed.stderr or "")
        raise RuntimeError(detail.strip() or "The ICIR feed refresh failed without an error message.")
    st.cache_data.clear()
    st.rerun()


def build_story_preview_summary(story):
    if not isinstance(story, dict):
        return "No summary available."

    url = story.get("url") or ""
    title = story.get("title") or "Untitled story"
    category = story.get("category") or "General"

    try:
        if url:
            article_text = get_article_text(url)
            if article_text:
                payload = {
                    "title": title,
                    "category": category,
                    "url": url,
                    "text": article_text,
                }
                result = summarize_story(payload)
                if result and result.get("summary"):
                    return result["summary"]
    except Exception:
        pass

    summary_text = story.get("summary") or story.get("text") or title
    return trim_newsletter_summary(summary_text) or title


def get_approved_summary_candidates(df, limit=5):
    if df is None or df.empty:
        return pd.DataFrame(columns=["select", "order", "title", "category", "url", "summary"])

    approved = df[df.get("select", False)].copy()
    if approved.empty:
        return approved

    return approved.sort_values("order").head(limit).reset_index(drop=True)


def build_newsletter_script(selected_df):
    selected = selected_df[selected_df["select"]].copy()
    if selected.empty:
        return "No approved stories selected yet."

    selected = selected.sort_values("order").head(5).reset_index(drop=True)
    lines = []
    for idx, row in enumerate(selected.itertuples(index=False), start=1):
        title = getattr(row, "title", "")
        summary = clean_story_text(getattr(row, "summary", "") or "")
        if summary:
            lines.append(f"{idx}. {title}\n{summary}")
        else:
            lines.append(f"{idx}. {title}")

    script = "Good morning, welcome to today's ICIR briefing.\n\n"
    script += "\n\n".join(lines)
    script += "\n\nThat is all for today's briefing."
    return script


def generate_final_audio_from_approved(selected_df, script_override=None, tts_provider="elevenlabs", tts_secrets=None):
    approved = selected_df[selected_df["select"]].copy()
    if approved.empty:
        raise ValueError("No approved stories selected. Choose at least one story before generating audio.")

    script_text = script_override if script_override is not None else build_newsletter_script(selected_df)
    if not script_text or not script_text.strip():
        script_text = build_newsletter_script(selected_df)

    FINAL_SCRIPT_PATH.write_text(script_text, encoding="utf-8")

    output_dir = AUDIO_GENERATED_DIR
    output_dir.mkdir(exist_ok=True)
    output_name = f"icir_newsletter_manual_{datetime.now():%Y%m%d_%H%M%S_%f}.mp3"
    output_path = output_dir / output_name
    cmd = [sys.executable, str(ROOT / "newsletter_audio.py")]
    cmd.extend(["--output", str(output_path)])
    child_env = dict(__import__("os").environ)
    child_env["TTS_PROVIDER"] = tts_provider
    for key, value in (tts_secrets or {}).items():
        if value:
            child_env[key] = str(value)
    completed = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, env=child_env)

    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "Audio generation failed.")
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("Audio generation reported success, but the MP3 file was not created.")

    return script_text, completed.stdout.strip(), output_name, output_path.read_bytes()


st.set_page_config(page_title="ICIR Story Review", page_icon="📰", layout="wide")
st.title("ICIR Newsletter Review Dashboard")

with st.sidebar:
    st.header("Controls")
    automation_enabled = st.toggle(
        "Enable Friday 8:00 AM automation",
        value=load_automation_state().get("enabled", False),
        help="This enables or disables the runner. Create the weekly task separately in Windows Task Scheduler; see PROJECT_STATUS.md.",
    )
    if st.button("Save automation setting"):
        save_automation_state(automation_enabled)
        st.success(f"Friday automation is now {'enabled' if automation_enabled else 'disabled'}.")

    if st.button("Refresh stories from ICIR feed"):
        try:
            refresh_stories()
        except (subprocess.CalledProcessError, RuntimeError) as exc:
            st.error(f"Refresh failed: {exc}")

    st.caption("This pulls the latest ICIR feed and updates the review list.")
    st.caption("Create a weekly Friday task in Windows Task Scheduler as described in PROJECT_STATUS.md. It uses only the approved story list and exact saved script for that Friday, and creates an MP3 without sending it.")

    st.markdown("---")
    st.caption(f"Stories file: {STORIES_PATH.name}")

stories_df = load_stories()

if stories_df.empty:
    st.warning("No stories are available yet. Click the refresh button to pull the latest ICIR feed.")
    st.stop()

st.subheader("Live story shortlist")

edited = st.data_editor(
    stories_df,
    width="stretch",
    hide_index=True,
    column_order=["select", "order", "title", "category", "summary", "url"],
    disabled=["order", "title", "category", "url"],
    column_config={
        "select": st.column_config.CheckboxColumn(
            "Approve",
            help="Tick the stories that should go into the newsletter.",
            default=False,
        ),
        "summary": st.column_config.TextColumn("Summary", width="large"),
        "url": st.column_config.LinkColumn("URL"),
    },
)

approved_summary_stories = get_approved_summary_candidates(edited, limit=5)
if not approved_summary_stories.empty:
    st.subheader("Selected story summaries")
    columns = st.columns(len(approved_summary_stories))

    for idx, (_, picked_story) in enumerate(approved_summary_stories.iterrows()):
        with columns[idx]:
            st.markdown(f"### {picked_story['title']}")
            st.caption(f"{picked_story['category']} • {picked_story['url']}")
            summary_text = build_story_preview_summary(picked_story.to_dict())
            st.write(summary_text)
else:
    st.caption("Approve up to five stories in the shortlist above to preview their summaries here.")

approved_df = edited[edited["select"]].copy()

st.markdown("---")
col1, col2 = st.columns(2)

with col1:
    st.metric("Total stories", len(stories_df))
    st.metric("Approved stories", len(approved_df))

with col2:
    category_counts = stories_df.groupby("category").size().sort_values(ascending=False)
    st.write("Category summary")
    st.dataframe(category_counts.rename("count").reset_index(), width="stretch")

st.subheader("Approved story preview")
if approved_df.empty:
    st.info("No stories approved yet. Select stories using the checkboxes above.")
else:
    st.dataframe(approved_df[["order", "title", "category", "url"]], width="stretch")

st.markdown("---")

approved_story_keys = tuple(
    (str(row["title"]), str(row["url"]))
    for _, row in edited[edited["select"]].sort_values("order").iterrows()
)
current_script = build_newsletter_script(edited)
last_approved_key = st.session_state.get("last_approved_story_keys")

if (
    "draft_script" not in st.session_state
    or not st.session_state["draft_script"].strip()
    or last_approved_key != approved_story_keys
):
    st.session_state["draft_script"] = current_script
    st.session_state["last_approved_story_keys"] = approved_story_keys

st.subheader("Newsletter draft script")
st.info(
    "Review and edit this script before approval. The Friday job will use the exact script saved with the approved story list.",
    icon="📝",
)
user_draft = st.text_area(
    "Draft script",
    value=st.session_state["draft_script"],
    height=220,
    help="This starts from the approved shortlist. The Friday job uses this exact text only after you approve and save the edition below.",
)
if approved_story_keys != st.session_state.get("last_approved_story_keys"):
    st.session_state["last_approved_story_keys"] = approved_story_keys
st.session_state["draft_script"] = user_draft

today = date.today()
days_to_friday = (4 - today.weekday()) % 7
default_issue_date = today + timedelta(days=days_to_friday)
approval_issue_date = st.date_input(
    "Friday edition date for these approvals",
    value=default_issue_date,
    help="The scheduled job will refuse to generate audio unless the saved approvals match the Friday it is running for.",
)
if st.button("Approve and save Friday edition"):
    try:
        approved_count = save_approval(edited, user_draft, approval_issue_date)
        st.success(f"Approved and saved {approved_count} stories and the final script for {approval_issue_date.isoformat()}.")
    except (ValueError, OSError) as exc:
        st.error(str(exc))

if st.button("Save final draft script"):
    FINAL_SCRIPT_PATH.write_text(user_draft, encoding="utf-8")
    st.session_state["saved_draft_download"] = {
        "text": user_draft,
        "filename": f"icir_newsletter_draft_{datetime.now():%Y%m%d_%H%M%S_%f}.txt",
    }
    st.success(f"Saved final draft script to {FINAL_SCRIPT_PATH.name}")

saved_draft = st.session_state.get("saved_draft_download")
if saved_draft and saved_draft.get("text") == user_draft:
    st.download_button(
        "Download saved draft script",
        data=saved_draft["text"],
        file_name=saved_draft["filename"],
        mime="text/plain; charset=utf-8",
        key="download_saved_newsletter_draft",
    )

provider_options = ["elevenlabs", "kittenml"]
default_provider_index = 1 if os.getenv("TTS_PROVIDER", "elevenlabs").strip().lower() == "kittenml" else 0
tts_provider = st.selectbox(
    "Audio provider",
    provider_options,
    index=default_provider_index,
    help="KittenML runs generation in its hosted API, so it does not use your computer's CPU.",
)
audio_signature = hashlib.sha256(
    json.dumps(
        {"script": user_draft, "stories": approved_story_keys, "provider": tts_provider},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
).hexdigest()
saved_audio = st.session_state.get("generated_audio")
if saved_audio and saved_audio.get("signature") != audio_signature:
    st.session_state.pop("generated_audio", None)

if st.button("Generate final audio after approval"):
    if approved_df.empty:
        st.warning("You must approve at least one story before generating the final audio.")
    else:
        try:
            secret_values = {}
            try:
                secret_values["KITTENML_API_KEY"] = st.secrets.get("KITTENML_API_KEY", "")
                secret_values["KITTENML_VOICE_ID"] = st.secrets.get("KITTENML_VOICE_ID", "")
                secret_values["ELEVENLABS_API_KEY"] = st.secrets.get("ELEVENLABS_API_KEY", "")
                secret_values["ELEVENLABS_VOICE_ID"] = st.secrets.get("ELEVENLABS_VOICE_ID", "")
            except Exception:
                pass
            _, output_text, audio_filename, audio_bytes = generate_final_audio_from_approved(
                edited, script_override=user_draft, tts_provider=tts_provider, tts_secrets=secret_values
            )
            st.session_state["generated_audio"] = {
                "signature": audio_signature,
                "filename": audio_filename,
                "data": audio_bytes,
            }
            st.success("Final audio generated successfully. Download it below.")
            st.code(output_text)
        except Exception as exc:
            st.error(f"Audio generation failed: {exc}")

saved_audio = st.session_state.get("generated_audio")
if saved_audio and saved_audio.get("signature") == audio_signature:
    st.download_button(
        "Download generated MP3",
        data=saved_audio["data"],
        file_name=saved_audio["filename"],
        mime="audio/mpeg",
        key="download_generated_newsletter_audio",
    )

st.caption("This dashboard keeps editorial approval in the loop before audio generation. It does not send or publish the newsletter.")

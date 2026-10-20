# ICIR Newsletter Workflow

A Streamlit dashboard for the ICIR editor to refresh stories, review and edit the newsletter, save an approval, generate narration, and download the final script or MP3.

## Run locally

1. Use Python 3.11 or newer.
2. Install dependencies: `python -m pip install -r requirements.txt`.
3. Copy `config/.env.example` to `config/.env` and enter credentials in that local file. Never commit `config/.env`.
4. Start the dashboard: `streamlit run streamlit_app.py`.

Set `TTS_PROVIDER` to `kittenml` or `elevenlabs`. KittenML is the default for this project.

## Deploy on Streamlit Community Cloud

1. Create an app from this repository and select `streamlit_app.py` as the entry point.
2. In Advanced settings, add `GOOGLE_API_KEY`, `KITTENML_API_KEY`, `KITTENML_VOICE_ID`, and `TTS_PROVIDER` in the app's Secrets field. Add `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` only if using ElevenLabs. `OPENAI_API_KEY` is optional and is used as a fallback for summarization.
3. This repository is public, so Community Cloud makes the app public by default. Before sharing the URL, open the app's Sharing settings and select **Only specific people can view this app**. Community Cloud currently allows one private app per workspace.

Do not put API keys in this repository, the README, or issue comments. Use the hosting provider's secret manager.

## Storage before production use

The app stores story, approval, and generated-audio files in local project folders. In a hosted deployment, those files are on the app server, not the editor's computer. Configure durable shared storage before relying on approvals or host-side files across restarts or redeployments. Editors can download the final script and MP3 from the dashboard.

Friday scheduling is not configured. Editor approval remains separate from audio generation.

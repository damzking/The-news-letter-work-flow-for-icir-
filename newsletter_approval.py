"""Save and verify an editor-approved Friday newsletter edition."""
import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from project_paths import APPROVAL_PATH, FINAL_SCRIPT_PATH, NEWSLETTER_DIR, REVIEW_PATH

SCRIPT_PATH = FINAL_SCRIPT_PATH
MANIFEST_PATH = APPROVAL_PATH
MAX_STORIES = 5


def _atomic_write(path, content):
    NEWSLETTER_DIR.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="")
    temporary.replace(path)


def save_approval(edited_df, script_text, issue_date):
    if issue_date.weekday() != 4:
        raise ValueError("Choose a Friday edition date before approving the newsletter.")
    if not script_text or not script_text.strip():
        raise ValueError("The final newsletter script is empty.")

    review_df = edited_df.copy()
    review_df = review_df[["order", "title", "category", "url", "summary", "select"]]
    approved = review_df["select"].astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})
    approved_count = int(approved.sum())
    if approved_count == 0:
        raise ValueError("Approve at least one story before saving the Friday edition.")
    if approved_count > MAX_STORIES:
        raise ValueError("Approve no more than five stories; the newsletter supports up to five.")

    review_df = review_df.rename(columns={"select": "approved"})
    review_df["approved"] = approved
    review_df["approved_for"] = issue_date.isoformat()
    review_csv = review_df.to_csv(index=False, lineterminator="\n")
    review_hash = hashlib.sha256(review_csv.encode("utf-8")).hexdigest()
    manifest = {
        "status": "approved",
        "approved_for": issue_date.isoformat(),
        "approved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "approved_count": approved_count,
        "review_sha256": review_hash,
        "script": script_text.strip(),
    }

    # Invalidate the prior approval before changing any saved review data.
    _atomic_write(MANIFEST_PATH, json.dumps({"status": "saving"}) + "\n")
    _atomic_write(REVIEW_PATH, review_csv)
    _atomic_write(SCRIPT_PATH, manifest["script"] + "\n")
    _atomic_write(MANIFEST_PATH, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return approved_count


def load_approval(issue_date):
    if not MANIFEST_PATH.is_file() or not REVIEW_PATH.is_file():
        raise RuntimeError("No saved editor approval exists. Review and approve the Friday edition in the dashboard first.")

    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        review_csv = REVIEW_PATH.read_text(encoding="utf-8")
        review_df = pd.read_csv(REVIEW_PATH, dtype=str).fillna("")
    except (OSError, json.JSONDecodeError, pd.errors.ParserError) as exc:
        raise RuntimeError(f"Could not read the saved approval: {exc}") from exc

    if manifest.get("status") != "approved":
        raise RuntimeError("The saved approval is incomplete. Re-approve and save the Friday edition in the dashboard.")
    if manifest.get("approved_for") != issue_date.isoformat():
        saved_date = manifest.get("approved_for") or "unknown date"
        raise RuntimeError(
            f"The saved approval is for {saved_date}, not {issue_date.isoformat()}. "
            "The editor must approve and save this Friday's edition before audio can be generated."
        )

    actual_hash = hashlib.sha256(review_csv.encode("utf-8")).hexdigest()
    if manifest.get("review_sha256") != actual_hash:
        raise RuntimeError("The saved review changed after approval. Re-approve and save it in the dashboard before running.")

    required = {"approved", "approved_for", "title", "summary"}
    if not required.issubset(review_df.columns):
        raise RuntimeError("The approval CSV is incomplete. Re-approve and save the Friday edition in the dashboard.")

    approved_flags = review_df["approved"].str.strip().str.lower().isin({"true", "1", "yes", "y"})
    approved = review_df.loc[approved_flags].copy()
    count = len(approved)
    if count == 0 or count > MAX_STORIES or count != manifest.get("approved_count"):
        raise RuntimeError("The approved story count is invalid. Re-approve and save the Friday edition in the dashboard.")
    if not approved["approved_for"].str.strip().eq(issue_date.isoformat()).all():
        raise RuntimeError("The saved stories do not match this Friday's approval date. Re-approve and save them.")
    if not approved["title"].str.strip().ne("").all():
        raise RuntimeError("An approved story has no title. Fix and save the review before running.")

    script = manifest.get("script", "")
    if not isinstance(script, str) or not script.strip():
        raise RuntimeError("The approved script is empty. Re-approve and save it in the dashboard.")

    return approved.to_dict(orient="records"), script.strip()

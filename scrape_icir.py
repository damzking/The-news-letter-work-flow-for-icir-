import argparse
import csv
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from project_paths import STORIES_CSV_PATH, STORIES_PATH

load_dotenv(Path(__file__).resolve().parent / "config" / ".env", override=True)

HOME = "https://www.icirnigeria.org/"
FEED = "https://www.icirnigeria.org/feed/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NewsletterBot/0.1; personal learning project)"}
SKIP = ("/category/", "/tag/", "/author/", "/latest/", "/video-cat/")
REQUEST_DELAY = 1.2
JINA_PREFIX = "https://r.jina.ai/"


def to_jina_url(url):
    """Convert an ICIR URL to Jina's reader proxy format."""
    return f"{JINA_PREFIX}{url}" if not url.startswith(JINA_PREFIX) else url


def fetch(url, retries=3):
    """Fetch ICIR content via Jina when direct requests are rate-limited."""
    target_url = to_jina_url(url) if "icirnigeria.org" in url else url
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(target_url, headers=HEADERS, timeout=30)
            if resp.status_code == 429:
                raise requests.exceptions.HTTPError(f"429 Too Many Requests for {url}")
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(REQUEST_DELAY * attempt)
                continue
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def normalize_category(value):
    """Convert category strings into a clean label."""
    if not value:
        return "Uncategorized"
    text = value.strip().replace("\n", " ")
    return " ".join(text.split())


def trim_newsletter_summary(text, max_words=140):
    """Trim article-like text into a concise newsletter summary."""
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)

    summary = clean_story_text(text)
    if not summary:
        return ""

    words = re.findall(r"\S+", summary)
    if len(words) <= max_words:
        return summary

    sentences = re.split(r"(?<=[.!?])\s+", summary)
    kept = []
    current_words = 0
    for sentence in sentences:
        sentence_words = re.findall(r"\S+", sentence)
        if current_words + len(sentence_words) > max_words:
            remaining = max_words - current_words
            if remaining <= 0:
                break
            compact = " ".join(sentence_words[:remaining])
            kept.append(compact.rstrip(".,;:!?"))
            break
        kept.append(sentence.strip())
        current_words += len(sentence_words)

    final = " ".join(part.strip() for part in kept if part.strip())
    if not final:
        final = " ".join(words[:max_words])
    if final and not final.endswith(".") and not final.endswith("!") and not final.endswith("?"):
        final += "."
    return final.strip()


def clean_story_text(text):
    """Strip repeated Jina/site boilerplate and keep only the meaningful article copy."""
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"!\[[^\]]*\]\([^\)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+|#[^)]+)\)", r"\1", text)
    text = re.sub(r"\[\]\((https?://[^\s)]+|#[^)]+)\)", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = text.replace("**", "").replace("__", "")

    noise_markers = (
        "human rights accountability and justice issues",
        "promoting social justice and accountability in west africa",
        "africa resilience network",
        "useful tips for journalists reporting ebola",
        "title:",
        "url source:",
        "published time:",
        "read more",
        "author",
        "source:",
    )

    cleaned_lines = []
    seen = set()
    for raw_line in text.splitlines():
        line = re.sub(r"^#+\s*", "", raw_line).strip()
        line = re.sub(r"^\*+\s*", "", line)
        line = re.sub(r"^[-•]\s*", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        lower_line = line.lower()
        if any(re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", lower_line) for marker in noise_markers):
            continue
        if line.startswith("http"):
            continue
        if len(line) < 20 and not any(ch in line for ch in ".!?"):
            continue
        normalized = re.sub(r"\s+", " ", line)
        lower = normalized.lower()
        if lower in seen:
            continue
        seen.add(lower)
        cleaned_lines.append(normalized)

    cleaned = "\n\n".join(cleaned_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    paragraphs = []
    for piece in re.split(r"\n\s*\n+", cleaned):
        sentences = []
        seen_sentences = set()
        for sentence in re.split(r"(?<=[.!?])\s+", piece.strip()):
            candidate = re.sub(r"\s+", " ", sentence).strip()
            if not candidate:
                continue
            key = candidate.lower()
            if key in seen_sentences:
                continue
            seen_sentences.add(key)
            sentences.append(candidate)
        if sentences:
            paragraphs.append(" ".join(sentences))
    cleaned = "\n\n".join(paragraphs)
    return cleaned.strip()


def parse_homepage(content, limit=5):
    """Return up to `limit` unique article links in homepage order."""
    if not content:
        return []

    text = content.strip()
    if "<" in text and ">" in text and "href" in text.lower():
        soup = BeautifulSoup(content, "html.parser")
        stories, seen = [], set()
        for h3 in soup.select("h3"):
            link = h3.find("a", href=True)
            if not link:
                continue
            url = urljoin(HOME, link["href"])
            title = link.get_text(" ", strip=True)
            if not title or url in seen or any(part in url for part in SKIP):
                continue
            seen.add(url)

            block = h3.find_parent(["article", "div", "li"])
            category_link = None
            if block:
                category_link = block.find("a", href=lambda h: h and "/category/" in h)
            category = normalize_category(category_link.get_text(" ", strip=True) if category_link else None)

            stories.append({
                "title": title,
                "url": url,
                "category": category,
            })
            if len(stories) == limit:
                break
        return stories

    stories, seen = [], set()
    pattern = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
    for title, url in pattern.findall(text):
        clean_url = urljoin(HOME, url)
        clean_title = normalize_category(title)
        if not clean_title or clean_url in seen or clean_url == HOME or any(part in clean_url for part in SKIP):
            continue
        seen.add(clean_url)
        stories.append({
            "title": clean_title,
            "url": clean_url,
            "category": "Uncategorized",
        })
        if len(stories) == limit:
            break
    return stories


def parse_feed(xml_text, limit=5):
    """Return the newest `limit` items from an RSS feed or a Jina markdown proxy view."""
    text = (xml_text or "").strip()
    if text.startswith("<"):
        root = ET.fromstring(text)
        stories = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            summary_html = item.findtext("description") or ""
            summary_text = BeautifulSoup(summary_html, "html.parser").get_text(" ", strip=True)
            category = infer_category(title, summary_text)
            stories.append({
                "title": title,
                "url": (item.findtext("link") or "").strip(),
                "published": item.findtext("pubDate"),
                "summary": summary_text,
                "category": category,
            })
            if len(stories) == limit:
                break
        return stories

    return parse_feed_markdown(text, limit=limit)


def parse_feed_markdown(markdown_text, limit=5):
    """Parse Jina-rendered RSS markdown into real article objects."""
    stories, seen = [], set()
    pattern = re.compile(r"### \[([^\]]+)\]\((https?://[^\s)]+)\)")
    for title, url in pattern.findall(markdown_text or ""):
        clean_url = urljoin(HOME, url)
        clean_title = title.strip()
        if not clean_title or clean_url in seen or any(part in clean_url for part in SKIP):
            continue
        seen.add(clean_url)
        stories.append({
            "title": clean_title,
            "url": clean_url,
            "published": None,
            "summary": "",
            "category": infer_category(clean_title),
        })
        if len(stories) == limit:
            break
    return stories


def infer_category(title, content=""):
    """Infer a customer-friendly category from a story title/body."""
    text = f"{title} {content}".lower()
    categories = {
        "Politics": ["election", "governance", "politics", "senate", "president", "minister", "inec", "judiciary", "legislature", "court", "government"],
        "Business": ["economy", "market", "bank", "finance", "trade", "oil", "tax", "investment", "banking", "manufacturing", "energy", "currency"],
        "Health": ["health", "covid", "hospital", "medical", "disease", "clinic", "malaria", "vaccine"],
        "Environment": ["climate", "environment", "water", "flood", "energy", "waste", "pollution"],
        "Security": ["security", "police", "crime", "military", "defence", "conflict", "bandit", "violence"],
        "Education": ["school", "education", "student", "university", "teacher", "academy"],
        "Technology": ["tech", "digital", "ai", "software", "internet", "telecom", "cyber"],
        "Sports": ["football", "sports", "athlete", "match", "league", "club"],
    }
    for category, keywords in categories.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "General"


def fetch_story_details(url, limit_chars=5000):
    """Fetch one article through Jina and return a customer-ready article payload."""
    page = fetch(url)
    lines = page.splitlines()
    title = next((line.split(":", 1)[1].strip() for line in lines if line.lower().startswith("title:")), "") or ""
    published = next((line.split(":", 1)[1].strip() for line in lines if line.lower().startswith("published time:")), "") or ""
    content = "\n".join(lines[lines.index(next((line for line in lines if "Markdown Content:" in line), "")) + 1:]) if any("Markdown Content:" in line for line in lines) else page
    content = re.sub(r"^#+\s*", "", content, flags=re.M)
    text_only = clean_story_text(content)
    text_only = re.sub(r"\*+|_+|`+", "", text_only)
    text_only = "\n".join(line.strip() for line in text_only.splitlines() if line.strip())
    category = infer_category(title, text_only)
    return {
        "title": title,
        "url": url,
        "published": published,
        "category": category,
        "text": text_only[:limit_chars],
        "summary": text_only[:1200],
    }


def group_stories_by_category(stories, items_per_category=10, category_limit=None, limit=None):
    """Group stories by category, capping both story count and category count."""
    if limit is not None and items_per_category == 10:
        items_per_category = limit

    grouped = defaultdict(list)
    for story in stories:
        category = normalize_category(story.get("category") or story.get("section") or "Uncategorized")
        grouped[category].append(story)

    ordered = dict(sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])))
    if category_limit is not None:
        ordered = dict(list(ordered.items())[:category_limit])
    if items_per_category is not None:
        ordered = {key: value[:items_per_category] for key, value in ordered.items()}
    return ordered


def get_article_text(url):
    """Download one article and return its main paragraphs as plain text."""
    content = fetch(url)
    if "<" in content and ">" in content:
        soup = BeautifulSoup(content, "html.parser")
        box = soup.select_one("div.entry-content") or soup.find("article") or soup
        paragraphs = [p.get_text(" ", strip=True) for p in box.find_all("p")]
        cleaned = [clean_story_text(p) for p in paragraphs if p and len(p) > 40]
        return "\n\n".join(p for p in cleaned if p)

    cleaned = clean_story_text(content)
    lines = []
    for line in cleaned.splitlines():
        stripped = re.sub(r"^#+\s*", "", line).strip()
        if len(stripped) > 40:
            lines.append(stripped)
    return "\n".join(lines)


def summarize_story_with_google(story, api_key=None, model="gemini-3.8-flash"):
    """Try Google AI Studio first for polished newsletter summaries."""
    if api_key is None:
        api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None

    try:
        from google import genai

        title = (story or {}).get("title", "Untitled story").strip()
        category = (story or {}).get("category") or "General"
        text = (story or {}).get("text") or (story or {}).get("summary") or ""
        text = clean_story_text(text)
        text = re.sub(r"\s+", " ", text).strip() or title

        prompt = (
            "Write a premium business-style summary for a newsletter audience. "
            "Use 2 well-developed paragraphs, with the first paragraph covering the main facts and the second paragraph explaining the wider business, policy, or market impact. "
            "Make it substantial and readable, aiming for roughly 180 to 250 words total. "
            "Do not be overly brief. "
            "Return valid JSON with keys: headline, summary, impact, category. "
            "The summary field must be a plain string containing the two paragraphs joined by a newline newline. "
            "Make the summary useful for clients and executives.\n\n"
            f"Title: {title}\nCategory: {category}\nText: {text[:12000]}"
        )

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=model, contents=prompt)
        content = getattr(response, "text", None) or ""
        if not content:
            return None

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = {}

        summary_text = parsed.get("summary") or content
        if isinstance(summary_text, str):
            summary_text = summary_text.strip()

        return {
            "headline": parsed.get("headline") or title,
            "summary": summary_text,
            "impact": parsed.get("impact") or "This story may affect planning, risk, or customer decisions.",
            "category": parsed.get("category") or category,
            "source_url": (story or {}).get("url"),
        }
    except Exception:
        return None


def summarize_story(story, api_key=None, model="gpt-4o-mini"):
    """Create a customer-ready summary for one story. Prefers Google AI Studio when configured, then OpenAI, then fallback."""
    title = (story or {}).get("title", "Untitled story").strip()
    category = (story or {}).get("category") or "General"
    text = (story or {}).get("text") or (story or {}).get("summary") or ""
    text = clean_story_text(text)
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        text = title

    google_key = os.getenv("GOOGLE_API_KEY")
    if google_key:
        google_summary = summarize_story_with_google(story, api_key=google_key)
        if google_summary:
            google_summary["summary"] = trim_newsletter_summary(google_summary.get("summary") or google_summary.get("headline") or title)
            return google_summary

    if api_key is None:
        api_key = os.getenv("OPENAI_API_KEY")

    if api_key:
        try:
            import openai
            client = openai.OpenAI(api_key=api_key)
            prompt = (
                "Write a premium business-style summary for a newsletter audience. "
                "Use 2 well-developed paragraphs, with the first paragraph covering the main facts and the second paragraph explaining the wider business, policy, or market impact. "
                "Make it substantial and readable, aiming for roughly 180 to 250 words total. "
                "Do not be overly brief. "
                "Return valid JSON with keys: headline, summary, impact, category. "
                "The summary field must be a plain string containing the two paragraphs joined by a newline newline. "
                "Make the summary useful for clients and executives.\n\n"
                f"Title: {title}\nCategory: {category}\nText: {text[:12000]}"
            )
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            content = response.choices[0].message.content
            parsed = json.loads(content)
            summary_text = parsed.get("summary") or content
            if isinstance(summary_text, str):
                summary_text = summary_text.strip()
            return {
                "headline": parsed.get("headline") or title,
                "summary": trim_newsletter_summary(summary_text),
                "impact": parsed.get("impact") or "This story may affect planning, risk, or customer decisions.",
                "category": parsed.get("category") or category,
                "source_url": (story or {}).get("url"),
            }
        except Exception:
            pass

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if sentences:
        core_sentences = sentences[:8]
        if len(core_sentences) < 4:
            core_sentences = sentences[:max(4, len(sentences))]

        para1 = " ".join(core_sentences[:4])
        para2_parts = [
            "The wider implication is that this development could influence policy, operations, investment decisions, and customer expectations in the short to medium term."
        ]
        para2_parts.extend(core_sentences[4:8])
        summary = para1 + "\n\n" + " ".join(para2_parts)
    else:
        summary = text[:1200]

    summary = trim_newsletter_summary(summary)
    impact = (
        "This matters because it could affect policy, operations, investment decisions, or customer expectations in the short to medium term."
    )
    return {
        "headline": title,
        "summary": summary,
        "impact": impact,
        "category": category,
        "source_url": (story or {}).get("url"),
    }


def summarize_stories(stories, api_key=None, model="gpt-4o-mini"):
    """Return a customer-ready list of story summaries."""
    return [summarize_story(story, api_key=api_key, model=model) for story in stories]


def export_grouped_csv(grouped, path):
    """Export grouped stories to a CSV file with one row per story."""
    rows = []
    for category, stories in grouped.items():
        for story in stories:
            rows.append({
                "category": category,
                "title": story.get("title", ""),
                "url": story.get("url", ""),
                "text": story.get("text", ""),
            })

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["category", "title", "url", "text"])
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)


def main():
    ap = argparse.ArgumentParser(description="Scrape top stories from The ICIR")
    ap.add_argument("--source", choices=["home", "feed"], default="feed")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--full", action="store_true", help="also fetch each article's text")
    ap.add_argument("--out", default=str(STORIES_PATH))
    ap.add_argument("--csv", default=str(STORIES_CSV_PATH), help="Optional CSV export path for grouped stories")
    ap.add_argument("--top-categories", type=int, default=10, help="Maximum number of categories to display")
    ap.add_argument("--stories-per-category", type=int, default=10, help="Maximum number of stories to keep in each category")
    args = ap.parse_args()

    try:
        if args.source == "home":
            stories = parse_homepage(fetch(HOME), args.limit)
        else:
            stories = parse_feed(fetch(FEED), args.limit)
    except RuntimeError as exc:
        print(f"Scraping failed: {exc}")
        print("Check your internet access, the ICIR feed, and Reader proxy availability, then try again.")
        raise SystemExit(1)

    if args.full:
        for story in stories:
            story["text"] = get_article_text(story["url"])
            story["summary"] = summarize_story(story).get("summary", story.get("title", ""))
    else:
        for story in stories:
            story["summary"] = summarize_story(story).get("summary", story.get("title", ""))

    grouped = group_stories_by_category(
        stories,
        items_per_category=args.stories_per_category,
        category_limit=args.top_categories,
    )

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"stories": stories, "by_category": grouped}, f, ensure_ascii=False, indent=2)

    csv_rows = export_grouped_csv(grouped, args.csv)

    print("Top stories:")
    for i, story in enumerate(stories, 1):
        print(f"{i}. {story['title']}\n   {story['url']}\n   Category: {story.get('category', 'Uncategorized')}")

    print("\nTop categories:")
    for category, items in grouped.items():
        print(f"- {category}: {len(items)} story(s)")

    print(f"\nSaved {len(stories)} stories to {args.out}")
    print(f"Saved {csv_rows} grouped stories to {args.csv}")


if __name__ == "__main__":
    main()

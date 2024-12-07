#!/usr/bin/env python3

import feedparser
import datetime
import re
import json
import os
from email.utils import parsedate_to_datetime
from atproto import Client, models
import time


class PaperTracker:
    def __init__(self, filename="posted_papers.json"):
        self.filename = filename
        self.posted_papers = self._load_posted_papers()

    def _load_posted_papers(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return []
        return []

    def _save_posted_papers(self):
        with open(self.filename, "w") as f:
            json.dump(self.posted_papers, f)

    def is_posted(self, arxiv_id):
        return arxiv_id in self.posted_papers

    def mark_as_posted(self, arxiv_id):
        if arxiv_id not in self.posted_papers:
            self.posted_papers.append(arxiv_id)
            self._save_posted_papers()


def connect_to_bluesky(username, password):
    client = Client()
    client.login(username, password)
    return client


def clean_summary(summary):
    """Extract and clean the abstract from the summary text."""
    abstract_pos = summary.lower().find("abstract:")
    if abstract_pos != -1:
        clean_text = summary[abstract_pos:].strip()
        return clean_text
    return summary


def create_post_with_link(client, paper):
    """Create a Bluesky post with properly formatted link after the title."""
    # Clean and truncate the summary
    clean_abstract = clean_summary(paper["summary"])
    short_summary = (
        clean_abstract[:250] if len(clean_abstract) > 250 else clean_abstract
    )

    # Start with the title
    title_text = f"arxiv 📄 {paper['title'].strip()}\n"

    # Calculate where the link will go
    link_start = len(title_text)
    link_end = link_start + len(paper["link"])

    # Create the full post text
    post_text = f"{title_text}\n\n{paper['link']}\n{short_summary}"

    # Create facet for the URL
    facets = [
        models.AppBskyRichtextFacet.Main(
            features=[models.AppBskyRichtextFacet.Link(uri=paper["link"])],
            index=models.AppBskyRichtextFacet.ByteSlice(
                byteStart=link_start + 3, byteEnd=link_end + 5
            ),
        )
    ]

    # Ensure we don't exceed Bluesky's character limit
    if len(post_text) > 300:
        post_text = post_text[:297] + "..."

    return post_text, facets


def fetch_latest_papers(base_url):
    feed = feedparser.parse(base_url)

    papers = []
    for entry in feed.entries:
        try:
            published_date = parsedate_to_datetime(entry.published)
        except Exception:
            published_date = datetime.datetime.strptime(
                entry.published, "%Y-%m-%dT%H:%M:%SZ"
            )

        opt1 = re.search(r"coding", entry.summary, re.IGNORECASE)
        opt2 = re.search(r"programming", entry.summary, re.IGNORECASE)
        opt3 = re.search(r"bug", entry.summary, re.IGNORECASE)
        opt4 = re.search(r"testing", entry.summary, re.IGNORECASE)
        opt5 = re.search(r"verilog", entry.summary, re.IGNORECASE)

        if not opt1 and not opt2 and not opt3 and not opt4 and not opt5:
            continue

        opt1 = re.search(r"LLM", entry.summary, re.IGNORECASE)
        opt2 = re.search(r"Agent", entry.summary, re.IGNORECASE)

        if not opt1 and not opt2:
            continue

        paper = {
            "title": entry.title.strip(),
            "authors": [author.name for author in entry.authors],
            "published": published_date.strftime("%Y-%m-%d"),
            "link": entry.link,
            "summary": entry.summary,
            "arxiv_id": entry.id.split("/abs/")[-1],
        }
        papers.append(paper)

    return papers


def post_papers_to_bluesky(papers, client, tracker):
    for paper in papers:
        if tracker.is_posted(paper["arxiv_id"]):
            # print(f"Skipping already posted paper: {paper['title']}")
            continue

        try:
            post_text, facets = create_post_with_link(client, paper)
            client.send_post(text=post_text, facets=facets)
            tracker.mark_as_posted(paper["arxiv_id"])
            print(f"Posted paper: {paper['title']}")
            time.sleep(2)  # Rate limiting
        except Exception as e:
            print(f"Error posting paper: {paper['title']}")
            print(f"Error: {str(e)}")


if __name__ == "__main__":
    BLUESKY_USERNAME = os.getenv("BLUESKY_USERNAME")
    BLUESKY_PASSWORD = os.getenv("BLUESKY_PASSWORD")

    if not BLUESKY_USERNAME or not BLUESKY_PASSWORD:
        print("Please set BLUESKY_USERNAME and BLUESKY_PASSWORD environment variables")
        exit(1)

    tracker = PaperTracker()

    try:
        client = connect_to_bluesky(BLUESKY_USERNAME, BLUESKY_PASSWORD)
    except Exception as e:
        print(f"Failed to connect to Bluesky: {str(e)}")
        exit(1)

    base_url = "http://export.arxiv.org/api/query?search_query=cat:cs.AR+AND+(abs:LLM+OR+abs:Agent)&start=0&max_results=100&sortBy=submittedDate&sortOrder=descending"
    # base_url = 'http://export.arxiv.org/rss/cs.AR'
    papers = fetch_latest_papers(base_url)
    post_papers_to_bluesky(papers, client, tracker)

    base_url = "http://export.arxiv.org/api/query?search_query=cat:cs.SE+AND+(abs:LLM+OR+abs:Agent)&start=0&max_results=10&sortBy=submittedDate&sortOrder=descending"
    # base_url = 'http://export.arxiv.org/rss/cs.AR'
    papers = fetch_latest_papers(base_url)
    post_papers_to_bluesky(papers, client, tracker)

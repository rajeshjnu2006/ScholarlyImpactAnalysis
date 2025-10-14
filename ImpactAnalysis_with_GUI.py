import os
import sys
import subprocess
import time
import json
import requests
import pandas as pd
import networkx as nx
from urllib.parse import urlparse, parse_qs
from tkinter import Tk, Label, Entry, Button, StringVar, Text, END, ttk, filedialog, Scrollbar

# ===========================
# Dependency check
# ===========================
REQUIRED = ["pandas", "networkx", "requests", "serpapi", "openpyxl", "tqdm"]

def ensure_deps():
    for pkg in REQUIRED:
        try:
            __import__(pkg)
        except ImportError:
            print(f"Installing missing package: {pkg}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

ensure_deps()

from serpapi import GoogleSearch
from tqdm import tqdm

# ===========================
# Global config
# ===========================
SERPAPI_KEY = ""
LENS_API_TOKEN = ""
AUTHOR_ID = ""
MAX_PUBS = 5
MAX_CITES_PER_PUB = 50

CROSSREF_API = "https://api.crossref.org/works"
SERPAPI_PAGE_SIZE_AUTHOR = 100
SERPAPI_PAGE_SIZE_CITES = 10

SLEEP_AUTHOR_PAGE = 1.0
SLEEP_CITES_PAGE = 1.0
SLEEP_CROSSREF = 0.25
SLEEP_LENS = 0.5

OUTPUT_DIR = "scholar_outputs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ===========================
# Core functions (same as before)
# ===========================
def log(msg):
    """Helper to log into GUI text box."""
    console.insert(END, msg + "\n")
    console.see(END)
    root.update()

def get_publications(author_id: str) -> list:
    pubs = []
    start = 0
    while True:
        params = {
            "engine": "google_scholar_author",
            "author_id": author_id,
            "api_key": SERPAPI_KEY,
            "num": str(SERPAPI_PAGE_SIZE_AUTHOR),
            "start": str(start)
        }
        results = GoogleSearch(params).get_dict()
        articles = results.get("articles", [])
        if not articles:
            break
        pubs.extend(articles)
        has_next = results.get("serpapi_pagination", {}).get("next")
        if not has_next:
            break
        start += SERPAPI_PAGE_SIZE_AUTHOR
        time.sleep(SLEEP_AUTHOR_PAGE)
    return pubs

def extract_cites_id(cited_by_link: str) -> str | None:
    if not cited_by_link:
        return None
    try:
        parsed = urlparse(cited_by_link)
        q = parse_qs(parsed.query)
        if "cites" in q and q["cites"]:
            return q["cites"][0]
        if "cites=" in cited_by_link:
            return cited_by_link.split("cites=")[1].split("&")[0]
    except Exception:
        return None
    return None

def get_citing_articles_by_cites_id(cites_id: str, max_items: int) -> list:
    results_all = []
    start = 0
    while True:
        params = {
            "engine": "google_scholar",
            "api_key": SERPAPI_KEY,
            "start": start,
            "cites": cites_id
        }
        results = GoogleSearch(params).get_dict()
        articles = results.get("organic_results", [])
        if not articles:
            break
        results_all.extend(articles)
        if len(results_all) >= max_items:
            break
        has_next = results.get("serpapi_pagination", {}).get("next")
        if not has_next:
            break
        start += SERPAPI_PAGE_SIZE_CITES
        time.sleep(SLEEP_CITES_PAGE)
    return results_all[:max_items]

def crossref_lookup_type(title: str) -> str:
    if not title:
        return "unknown"
    try:
        r = requests.get(CROSSREF_API, params={"query.title": title, "rows": 1}, timeout=12)
        r.raise_for_status()
        items = r.json().get("message", {}).get("items", [])
        if items:
            return items[0].get("type", "unknown") or "unknown"
    except Exception:
        pass
    finally:
        time.sleep(SLEEP_CROSSREF)
    return "unknown"

def heuristic_classify(title: str, container: str) -> str:
    t = (title or "").lower()
    c = (container or "").lower()
    if any(w in t or w in c for w in ["review", "survey", "meta-analysis", "systematic review"]):
        return "review"
    if "patent" in t or "patent" in c:
        return "patent"
    if any(w in t or w in c for w in ["book", "chapter", "handbook", "monograph", "springer", "igi-global", "ieee press", "acm books"]):
        return "book"
    if any(w in t or w in c for w in ["thesis", "dissertation", "phd", "masters"]):
        return "thesis"
    return "unknown"

def classify_item(title: str, container: str):
    crossref_type = crossref_lookup_type(title)
    prelim = "unknown"
    if "review" in crossref_type:
        prelim = "review"
    elif "patent" in crossref_type:
        prelim = "patent"
    elif "book" in crossref_type or "chapter" in crossref_type:
        prelim = "book"
    if prelim == "unknown":
        prelim = heuristic_classify(title, container)
    return prelim, crossref_type, None

def safe_get(dic: dict, path: list, default=None):
    cur = dic or {}
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur

# ===========================
# Run analysis
# ===========================
def run_analysis():
    global SERPAPI_KEY, LENS_API_TOKEN, AUTHOR_ID, MAX_PUBS, MAX_CITES_PER_PUB

    AUTHOR_ID = scholar_id_var.get().strip()
    SERPAPI_KEY = serpapi_var.get().strip()
    LENS_API_TOKEN = lens_var.get().strip()
    mode = mode_var.get()

    if not AUTHOR_ID or not SERPAPI_KEY:
        log("Scholar ID and SerpAPI Key are required.")
        return

    log("Fetching publications...")
    pubs = get_publications(AUTHOR_ID)
    if not pubs:
        log("No publications found or API error.")
        return

    def safe_cite_count(pub):
        cited = pub.get("cited_by") or {}
        val = cited.get("value")
        return val if isinstance(val, int) else 0

    pubs = sorted(pubs, key=lambda p: safe_cite_count(p), reverse=True)
    total_pubs = len(pubs)
    log(f"Found {total_pubs} publications.")

    if mode == "Full":
        MAX_PUBS = total_pubs
        MAX_CITES_PER_PUB = 50
        log(f"Full mode: analyzing all {MAX_PUBS} publications, max {MAX_CITES_PER_PUB} citing items each.")
    else:
        MAX_PUBS = 1
        top_paper = pubs[0]
        top_citations = safe_cite_count(top_paper)
        if top_citations <= 50:
            MAX_CITES_PER_PUB = top_citations
        elif top_citations <= 200:
            MAX_CITES_PER_PUB = 100
        else:
            MAX_CITES_PER_PUB = 200
        log(f"Single mode: top paper has {top_citations} citations, fetching {MAX_CITES_PER_PUB} citing items.")

    rows = []
    for idx, pub in enumerate(pubs[:MAX_PUBS], 1):
        p_title = pub.get("title")
        log(f"Analyzing {idx}/{MAX_PUBS}: {p_title}")
        cited_by = pub.get("cited_by") or {}
        cite_count = cited_by.get("value", 0)
        link = cited_by.get("link")
        if not link or cite_count == 0:
            continue
        cites_id = extract_cites_id(link)
        citing_items = get_citing_articles_by_cites_id(cites_id, MAX_CITES_PER_PUB)
        for item in citing_items:
            c_title = item.get("title") or ""
            c_pub_info = safe_get(item, ["publication_info", "summary"], "")
            final_class, crossref_type, _ = classify_item(c_title, c_pub_info)
            rows.append({
                "cited_pub_title": p_title,
                "citing_title": c_title,
                "citing_container": c_pub_info,
                "final_class": final_class,
                "crossref_type": crossref_type
            })
        progress['value'] = (idx / MAX_PUBS) * 100
        root.update_idletasks()

    if not rows:
        log("No citing items found.")
        return

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUTPUT_DIR, "all_citations.csv"), index=False)
    with pd.ExcelWriter(os.path.join(OUTPUT_DIR, "citations_export.xlsx"), engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name="All")
    log(f"Export complete. Total citing items: {len(df)}")
    log(f"Saved to {OUTPUT_DIR}/all_citations.csv and citations_export.xlsx")

# ===========================
# GUI
# ===========================
root = Tk()
root.title("High Impact Citation Analyzer")
root.geometry("600x500")

Label(root, text="Google Scholar ID").pack()
scholar_id_var = StringVar()
Entry(root, textvariable=scholar_id_var, width=50).pack()

Label(root, text="SerpAPI Key").pack()
serpapi_var = StringVar()
Entry(root, textvariable=serpapi_var, width=50, show="*").pack()

Label(root, text="Lens.org API Token (optional)").pack()
lens_var = StringVar()
Entry(root, textvariable=lens_var, width=50, show="*").pack()

Label(root, text="Mode").pack()
mode_var = StringVar(value="Single")
ttk.Combobox(root, textvariable=mode_var, values=["Single", "Full"], width=20).pack()

Button(root, text="Start Analysis", command=run_analysis).pack(pady=10)

Label(root, text="Progress").pack()
progress = ttk.Progressbar(root, orient="horizontal", length=400, mode="determinate")
progress.pack(pady=5)

Label(root, text="Log").pack()
console = Text(root, height=12, width=70)
console.pack()
scroll = Scrollbar(root, command=console.yview)
console.config(yscrollcommand=scroll.set)
scroll.pack(side="right", fill="y")

root.mainloop()

import os
import sys
import subprocess
import time
import json
import requests
import pandas as pd
import networkx as nx
from urllib.parse import urlparse, parse_qs

# ===========================
# Dependency check and install
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
# Global configuration
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

OUTPUT_DIR = "scholar_outputs_with_progress_bar"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ===========================
# Helper functions
# ===========================
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

def lens_patent_search_by_title(title: str) -> dict | None:
    if not title or not LENS_API_TOKEN or LENS_API_TOKEN.startswith("YOUR_"):
        return None
    url = "https://api.lens.org/patent/search"
    headers = {"Authorization": f"Bearer {LENS_API_TOKEN}", "Content-Type": "application/json"}
    body = {"query": {"bool": {"must": [{"match": {"title": {"query": title}}}]}},
            "size": 1,
            "include": ["lens_id","title","jurisdiction","publication_number","publication_date","family_id","applicants","owners","inventors"]}
    try:
        resp = requests.post(url, headers=headers, data=json.dumps(body), timeout=20)
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("data", []) or data.get("results", []) or []
        if hits:
            hit = hits[0]
            return {
                "lens_id": hit.get("lens_id"),
                "title": hit.get("title"),
                "jurisdiction": hit.get("jurisdiction"),
                "publication_number": hit.get("publication_number"),
                "publication_date": hit.get("publication_date"),
                "family_id": hit.get("family_id"),
                "applicants": hit.get("applicants"),
                "owners": hit.get("owners"),
                "inventors": hit.get("inventors"),
            }
    except Exception:
        return None
    finally:
        time.sleep(SLEEP_LENS)
    return None

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
    lens_meta = None
    if prelim == "patent":
        lens_meta = lens_patent_search_by_title(title)
    return prelim, crossref_type, lens_meta

def safe_get(dic: dict, path: list, default=None):
    cur = dic or {}
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur

def build_graph_and_export(df: pd.DataFrame):
    G = nx.DiGraph()
    for pub_title in sorted(df["cited_pub_title"].dropna().unique()):
        G.add_node(f"PUB::{pub_title}", node_type="source_pub")
    for _, row in df.iterrows():
        pub_node = f"PUB::{row['cited_pub_title']}"
        cite_node = f"CITE::{row['citing_title']}"
        G.add_node(cite_node, node_type=row["final_class"] or "unknown")
        G.add_edge(pub_node, cite_node)
    gexf_path = os.path.join(OUTPUT_DIR, "citation_graph.gexf")
    graphml_path = os.path.join(OUTPUT_DIR, "citation_graph.graphml")
    nx.write_gexf(G, gexf_path)
    nx.write_graphml(G, graphml_path)
    return gexf_path, graphml_path

# ===========================
# Core logic with progress bar
# ===========================
def verify_top(pub):
    p_title = pub.get("title")
    cited_by = pub.get("cited_by") or {}
    cite_count = cited_by.get("value", 0)
    link = cited_by.get("link")
    if not link:
        print("No citations found for this publication.")
        return False
    cites_id = extract_cites_id(link)
    items = get_citing_articles_by_cites_id(cites_id, 10)
    print(f"Top cited paper: {p_title} | citing items retrieved: {len(items)}")
    return True

def run_full(pubs):
    rows = []
    with tqdm(total=len(pubs[:MAX_PUBS]), desc="Processing publications", unit="pub") as pbar:
        for idx, pub in enumerate(pubs[:MAX_PUBS], 1):
            p_title = pub.get("title")
            p_year = safe_get(pub, ["year"])
            cited_by = pub.get("cited_by") or {}
            cite_count = cited_by.get("value", 0)
            link = cited_by.get("link")
            if not link or cite_count == 0:
                pbar.update(1)
                continue
            cites_id = extract_cites_id(link)
            citing_items = get_citing_articles_by_cites_id(cites_id, MAX_CITES_PER_PUB)
            for item in citing_items:
                c_title = item.get("title") or ""
                c_url = item.get("link") or ""
                c_pub_info = safe_get(item, ["publication_info", "summary"], "")
                c_snippet = item.get("snippet") or ""
                final_class, crossref_type, lens_meta = classify_item(c_title, c_pub_info)
                rows.append({
                    "cited_pub_title": p_title,
                    "cited_pub_year": p_year,
                    "cited_by_count_at_scrape": cite_count,
                    "citing_title": c_title,
                    "citing_container": c_pub_info,
                    "citing_url": c_url,
                    "citing_snippet": c_snippet,
                    "final_class": final_class,
                    "crossref_type": crossref_type,
                    "lens_id": (lens_meta or {}).get("lens_id"),
                    "lens_publication_number": (lens_meta or {}).get("publication_number"),
                    "lens_publication_date": (lens_meta or {}).get("publication_date"),
                    "lens_jurisdiction": (lens_meta or {}).get("jurisdiction"),
                    "lens_family_id": (lens_meta or {}).get("family_id"),
                    "lens_applicants": json.dumps((lens_meta or {}).get("applicants")) if lens_meta else None,
                    "lens_owners": json.dumps((lens_meta or {}).get("owners")) if lens_meta else None,
                    "lens_inventors": json.dumps((lens_meta or {}).get("inventors")) if lens_meta else None,
                })
            pbar.update(1)

    if not rows:
        print("No citing items found.")
        return

    df = pd.DataFrame(rows)
    df_reviews = df[df["final_class"] == "review"]
    df_patents = df[df["final_class"] == "patent"]
    df_books = df[df["final_class"] == "book"]
    df_thesis = df[df["final_class"] == "thesis"]

    path_all_csv = os.path.join(OUTPUT_DIR, "all_citations.csv")
    path_reviews_csv = os.path.join(OUTPUT_DIR, "reviews_citing_you.csv")
    path_patents_csv = os.path.join(OUTPUT_DIR, "patents_citing_you.csv")
    path_books_csv = os.path.join(OUTPUT_DIR, "books_citing_you.csv")
    path_thesis_csv = os.path.join(OUTPUT_DIR, "theses_citing_you.csv")

    df.to_csv(path_all_csv, index=False)
    df_reviews.to_csv(path_reviews_csv, index=False)
    df_patents.to_csv(path_patents_csv, index=False)
    df_books.to_csv(path_books_csv, index=False)
    df_thesis.to_csv(path_thesis_csv, index=False)

    path_xlsx = os.path.join(OUTPUT_DIR, "citations_export.xlsx")
    with pd.ExcelWriter(path_xlsx, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name="All")
        df_reviews.to_excel(xw, index=False, sheet_name="Reviews")
        df_patents.to_excel(xw, index=False, sheet_name="Patents")
        df_books.to_excel(xw, index=False, sheet_name="Books")
        df_thesis.to_excel(xw, index=False, sheet_name="Theses")

    gexf_path, graphml_path = build_graph_and_export(df)
    print("\nExport complete")
    print(f"  All citations: {len(df)}")
    print(f"  Reviews: {len(df_reviews)} | Patents: {len(df_patents)} | Books: {len(df_books)} | Theses: {len(df_thesis)}")
    print(f"  CSVs and Excel saved in {OUTPUT_DIR}")
    print(f"  Graphs: {gexf_path}, {graphml_path}")

# ===========================
# Menu and control flow
# ===========================
def menu():
    global SERPAPI_KEY, LENS_API_TOKEN, AUTHOR_ID, MAX_PUBS, MAX_CITES_PER_PUB

    print("==============================")
    print(" High Impact Citation Analyzer")
    print("==============================")
    print("Default mode analyzes your most cited paper and sets citing limit automatically.")
    print("Type 'full' to analyze all your papers (can be expensive).")

    AUTHOR_ID = input("Enter Google Scholar ID: ").strip()
    SERPAPI_KEY = input("Enter SerpApi Key: ").strip()
    LENS_API_TOKEN = input("Enter Lens.org API Token (optional): ").strip()

    mode = input("Choose analysis mode [default=single / full]: ").strip().lower()
    full_mode = (mode == "full")

    print("\nFetching your publications...")
    pubs = get_publications(AUTHOR_ID)
    if not pubs:
        print("No publications found or API error.")
        return

    def safe_cite_count(pub):
        cited = pub.get("cited_by") or {}
        val = cited.get("value")
        return val if isinstance(val, int) else 0

    pubs = sorted(pubs, key=lambda p: safe_cite_count(p), reverse=True)
    if not pubs:
        print("No publications with citations found.")
        return
    total_pubs = len(pubs)
    print(f"Found {total_pubs} publications.")

    if full_mode:
        MAX_PUBS = total_pubs
        MAX_CITES_PER_PUB = 50
        print(f"➡ Full mode: analyzing all {MAX_PUBS} publications (max {MAX_CITES_PER_PUB} citing items each).")
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
        print(f"➡ Single mode: analyzing most cited paper")
        print(f"   Title: {top_paper.get('title')}")
        print(f"   Total citations: {top_citations}")
        print(f"   Citing items to fetch: {MAX_CITES_PER_PUB}")

    while True:
        print("\nMenu:")
        print("1. Verify using top cited publication (quick check)")
        print("2. Run analysis now")
        print("3. Exit")
        choice = input("Select option: ").strip()
        if choice == "1":
            verify_top(pubs[0])
        elif choice == "2":
            run_full(pubs)
        elif choice == "3":
            break
        else:
            print("Invalid choice.")

if __name__ == "__main__":
    menu()

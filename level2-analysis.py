import os
import re
import json
import pandas as pd
import requests

# --------------------------------------------------
# Configuration
# --------------------------------------------------
INPUT_FILE = "scholar_outputs_level1/all_citations.csv"
OUTPUT_DIR = "scholar_outputs_level2"
CACHE_FILE = "metadata_cache.json"
os.makedirs(OUTPUT_DIR, exist_ok=True)

LABEL_PRIORITY = [
    "patent",
    "thesis",
    "review",
    "conference",
    "journal",  # journal above book
    "book",
    "preprint",
    "unknown"
]

# --------------------------------------------------
# Helper functions
# --------------------------------------------------
def normalize(x):
    return str(x).strip().lower() if x is not None and not pd.isna(x) else ""

def match_any(patterns, text):
    return any(re.search(p, text) for p in patterns)

def is_patent_field(x):
    if x is None or pd.isna(x):
        return False
    s = str(x).strip().lower()
    return s not in ["", "nan", "none", "0"]

# --------------------------------------------------
# Metadata enrichment
# --------------------------------------------------
def extract_doi_from_url(url):
    url = normalize(url)
    m = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", url, re.I)
    return m.group(0) if m else None

def extract_arxiv_id(url):
    url = normalize(url)
    m = re.search(r"arxiv\.org/(abs|pdf)/([0-9]+\.[0-9]+)", url)
    return m.group(2) if m else None

def query_openalex(doi=None, arxiv_id=None):
    try:
        if doi:
            r = requests.get(f"https://api.openalex.org/works/https://doi.org/{doi}", timeout=8)
        elif arxiv_id:
            r = requests.get(f"https://api.openalex.org/works/arxiv:{arxiv_id}", timeout=8)
        else:
            return None
        if r.status_code == 200:
            return r.json()
    except Exception:
        return None
    return None

def query_crossref(doi):
    try:
        r = requests.get(f"https://api.crossref.org/works/{doi}", timeout=8)
        if r.status_code == 200:
            return r.json().get("message", {})
    except Exception:
        return None
    return None

def enrich_metadata(url, cache):
    doi = extract_doi_from_url(url)
    arxiv_id = extract_arxiv_id(url)
    key = f"doi:{doi}" if doi else f"arxiv:{arxiv_id}" if arxiv_id else None

    if key and key in cache:
        return cache[key]

    result = None
    if doi or arxiv_id:
        meta = query_openalex(doi, arxiv_id)
        if meta:
            result = {
                "source": "openalex",
                "type": meta.get("type"),
                "venue_type": (meta.get("host_venue") or {}).get("type"),
                "publisher": (meta.get("host_venue") or {}).get("publisher")
            }

    if doi and not result:
        meta = query_crossref(doi)
        if meta:
            result = {
                "source": "crossref",
                "type": meta.get("type"),
                "venue_type": None,
                "publisher": meta.get("publisher")
            }

    if key:
        cache[key] = result
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)

    return result

# --------------------------------------------------
# Classifier
# --------------------------------------------------
def classify_item(title, container, abstract, crossref_type,
                  lens_id, lens_pub_number, lens_family_id, url, meta):

    labels = {}
    t = normalize(title)
    c = normalize(container)
    a = normalize(abstract)
    u = normalize(url)
    cr = normalize(crossref_type)
    tcau = f"{t} {c} {a} {u} {cr}"

    meta_type = normalize(meta["type"]) if meta and meta.get("type") else ""
    meta_venue_type = normalize(meta["venue_type"]) if meta and meta.get("venue_type") else ""

    # 1. Patent (revised)
    patent_patterns = [
        r"patents\.google\.com",
        r"lens\.org",
        r"uspto\.gov",
        r"\bUS[\s-]*\d+[\s-]*[AB]\d+\b",
        r"\bEP[\s-]*\d+\b",
        r"\bWO[\s-]*\d+\b",
        r"\bCN[\s-]*\d+\b",
        r"\bKR[\s-]*\d+\b",
        r"\bJP[\s-]*\d+\b"
    ]
    if (
        is_patent_field(lens_id) or
        is_patent_field(lens_pub_number) or
        is_patent_field(lens_family_id) or
        match_any(patent_patterns, tcau)
    ):
        labels["patent"] = 5

    # 2. Thesis
    thesis_domains = [
        "search.proquest.com", "pqdtopen.proquest.com", "theses.fr", "ethos.bl.uk",
        "dspace", "etd.", "repository.", "hdl.handle.net", "openscholarship",
        "escholarship", ".library."
    ]
    if any(d in u for d in thesis_domains):
        labels["thesis"] = max(labels.get("thesis", 0), 5)
    if "thesis" in meta_type or "dissertation" in meta_type:
        labels["thesis"] = max(labels.get("thesis", 0), 5)
    if re.search(r"\b(thesis|dissertation|doctoral|phd|master('|)s)\b", t):
        labels["thesis"] = max(labels.get("thesis", 0), 4)
    if re.search(r"submitted\s+(to|by)", a) or \
       re.search(r"in partial fulfillment of the requirements", a) or \
       re.search(r"this (thesis|dissertation)", a):
        labels["thesis"] = max(labels.get("thesis", 0), 5)
    if "university" in c and re.search(r"thesis|dissertation|submitted to|graduate school|department", c):
        labels["thesis"] = max(labels.get("thesis", 0), 4)

    # 3. Review / Survey
    survey_phrases = [
        r"in this survey", r"in this review", r"this survey", r"this review",
        r"this paper (presents|provides|gives) (a )?(comprehensive )?(survey|review)",
        r"comprehensive survey", r"systematic review", r"literature review",
        r"overview of the state of the art", r"\bwe survey\b", r"\bwe review\b"
    ]
    if any(re.search(p, a) for p in survey_phrases):
        labels["review"] = max(labels.get("review", 0), 5)
    if re.search(r"^(a\s+(comprehensive\s+)?(survey|review)|systematic review)", t):
        labels["review"] = max(labels.get("review", 0), 5)
    if re.search(r"\bsurvey\b", t) or re.search(r"\breview\b", t):
        if not re.search(r"book review|peer review|double blind review", t):
            labels["review"] = max(labels.get("review", 0), 4)

    # 4. Conference
    lncs_patterns = [
        r"lecture notes in computer science", r"lecture notes in artificial intelligence",
        r"lecture notes in bioinformatics", r"\blncs\b", r"\blnai\b", r"\blnbi\b",
        r"/chapter/10\.1007/"
    ]
    if match_any(lncs_patterns, tcau) or meta_venue_type == "conference" or "proceedings" in t:
        labels["conference"] = max(labels.get("conference", 0), 4)

    # 5. Book
    strong_doi_prefixes = ["10.1007/978", "10.1016/B", "10.1201/", "10.1093/", "10.4324/"]
    book_publishers = ["cambridge.org", "elsevier", "taylorandfrancis", "oxfordacademic", "crcpress", "routledge"]
    book_keywords = [r"\bhandbook\b", r"\bencyclopedia\b", r"\btextbook\b", r"\bmonograph\b", r"\bspringerbriefs\b"]
    isbn_pattern = r"\b97[89][-\d]{10,}\b"

    strong_book = False
    medium_book = False

    if meta_type in ["book", "book-chapter", "edited-book", "monograph"]:
        strong_book = True

    if any(prefix in u for prefix in strong_doi_prefixes) or re.search(isbn_pattern, c) or "link.springer.com/book/" in u:
        strong_book = True

    if any(pub in u for pub in book_publishers) and not ("journal" in c or "journal-article" in cr or meta_venue_type == "journal"):
        medium_book = True
    if any(re.search(k, c) for k in book_keywords) or any(re.search(k, t) for k in book_keywords):
        medium_book = True

    if strong_book:
        labels["book"] = max(labels.get("book", 0), 5)
    elif medium_book:
        labels["book"] = max(labels.get("book", 0), 2)

    # Negative filters for book
    if "lncs" in c or "lecture notes in computer science" in c:
        labels.pop("book", None)
    if meta_venue_type == "journal" or "journal-article" in cr:
        labels.pop("book", None)
    if "journal" in c or "transactions" in c:
        labels.pop("book", None)
    if "symposium" in c or "conference" in c or "workshop" in c or "proceedings" in c:
        labels.pop("book", None)

    # 6. Journal
    if meta_venue_type == "journal" or "journal-article" in cr:
        labels["journal"] = max(labels.get("journal", 0), 4)
    if "journal" in c or "transactions" in c:
        labels["journal"] = max(labels.get("journal", 0), 3)

    # 7. Preprint
    if "researchgate.net" in u or "academia.edu" in u or "arxiv.org" in u:
        labels["preprint"] = max(labels.get("preprint", 0), 3)

    # 8. Unknown
    if not labels:
        labels["unknown"] = 0

    top_label = sorted(labels.keys(), key=lambda x: LABEL_PRIORITY.index(x))[0]
    return labels, top_label

# --------------------------------------------------
# Main pipeline
# --------------------------------------------------
def refine_csv(input_file):
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            try:
                cache = json.load(f)
            except json.JSONDecodeError:
                cache = {}
    else:
        cache = {}

    df = pd.read_csv(input_file)
    results = []
    for _, row in df.iterrows():
        meta = enrich_metadata(row.get("citing_url", ""), cache)
        labels, top_label = classify_item(
            row.get("citing_title", ""),
            row.get("citing_container", ""),
            row.get("citing_abstract", ""),
            row.get("crossref_type", ""),
            row.get("lens_id", None) or row.get("Lens ID", None),
            row.get("lens_publication_number", None) or row.get("Lens Publication Number", None),
            row.get("lens_family_id", None) or row.get("Lens Family ID", None),
            row.get("citing_url", ""),
            meta
        )
        r = row.to_dict()
        r["labels"] = ";".join(labels.keys())
        r["label_confidence"] = json.dumps(labels)
        r["top_label"] = top_label
        results.append(r)

    out_df = pd.DataFrame(results)
    out_df.to_csv(os.path.join(OUTPUT_DIR, "all_citations_refined.csv"), index=False)
    for label in LABEL_PRIORITY:
        subset = out_df[out_df["labels"].str.contains(label)]
        subset.to_csv(os.path.join(OUTPUT_DIR, f"{label}_citations.csv"), index=False)

    print(f"✅ Refinement complete. Results saved in '{OUTPUT_DIR}/'")
    print(f"  All refined: {len(out_df)}")
    for label in LABEL_PRIORITY:
        print(f"  {label.capitalize():<12}: {len(out_df[out_df['labels'].str.contains(label)])}")

# --------------------------------------------------
if __name__ == "__main__":
    refine_csv(INPUT_FILE)

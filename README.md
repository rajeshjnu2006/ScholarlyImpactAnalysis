# High-Impact Citation Analyzer

Analyze who cites your Google Scholar publications and categorize those citations into books, review or survey articles, patents, theses, and conferences. Built for researchers and non-programmers.

---

## What this tool does

* Fetches citing works for your publications from Google Scholar via [SerpAPI](https://serpapi.com/)
* Classifies citing works into:

  * Books and Book Chapters
  * Reviews and Surveys
  * Patents (optional via [Lens.org](https://www.lens.org) API)
  * Theses and Dissertations
  * Conferences and Proceedings
* Exports

  * CSVs and a single Excel file with one sheet per category
  * Citation graph files (GraphML, GEXF)
* Two analysis levels with complementary strengths:

  * Level 1 — Primary fetch and classification (uses API credits)
  * Level 2 — Offline refinement (no API calls)

---

## Strengths and Limitations of Levels

**Level 1 (Primary)**

* High recall. Tends to include most high-impact citations.
* May have more **false accepts** (e.g., conference proceedings labeled as books).
* Ideal for initial broad sweep of citations.

**Level 2 (Refinement)**

* High precision. Tends to remove misclassified entries.
* May have more **false rejects** (i.e., miss some real high-impact citations).
* Ideal when you want a cleaner, more conservative list of high-impact citations.

For best results, run Level 1 first, then Level 2. Compare both outputs to balance recall and precision.

---

## Prerequisites

* Python 3.9+
* SerpAPI key (required for Level 1)
* Lens.org API token (optional for patent enrichment)

Tkinter is required for GUI mode but is bundled with most Python installations.

---

## How to find your Google Scholar ID

1. Open your Google Scholar profile, for example: `https://scholar.google.com/citations?user=5cX99iUAAAAJ`
2. Copy the value after `?user=`. In this example it is `5cX99iUAAAAJ`.

---

## How to get a SerpAPI Key

1. Go to [https://serpapi.com/](https://serpapi.com/) and create an account.
2. Open your dashboard and copy your API Key.
3. Keep this key private.

Free plans have monthly credits. Start with single-paper mode to save calls.

---

## Optional: Lens.org API Token for patents

1. Create a free account at [https://www.lens.org](https://www.lens.org)
2. Go to User → API Access.
3. Generate and copy your token.

If you skip this, patent enrichment is disabled but everything else works.

---

## Install

```bash
git clone https://github.com/yourusername/impact-citation-analyzer.git
cd impact-citation-analyzer

python -m venv .venv
source .venv/bin/activate  # or .\.venv\Scripts\activate on Windows

pip install -r requirements.txt
```

If requirements.txt is not present, running the script once will auto-install needed packages.

---

## Level 1 — Primary Analysis

You can run GUI mode (recommended for beginners) or CLI mode.

### GUI mode

```bash
python level1_graphical.py
```

In the window:

* Enter Google Scholar ID
* Enter SerpAPI Key
* Enter Lens API Token (optional)
* Choose:

  * Single mode: analyzes only the most cited paper
  * Full mode: analyzes all publications in your profile
* Click Start Analysis

Outputs are saved in `scholar_outputs/`:

* `all_citations.csv`
* `books_citing_you.csv`
* `reviews_citing_you.csv`
* `patents_citing_you.csv`
* `theses_citing_you.csv`
* `conferences_citing_you.csv`
* `citations_export.xlsx`
* `citation_graph.gexf` and `citation_graph.graphml`

### CLI mode

```bash
python level1_analysis.py
```

Follow the prompts. Outputs are the same.

---

## Level 2 — Offline Refinement

If you already exported `all_citations.csv`, run a second pass to fix misclassified books (such as conference proceedings) without using any API credits.

```bash
python level2_analysis.py
```

Outputs are saved in `scholar_outputs_refined/`:

* `all_citations_refined.csv`
* `books_refined.csv`
* `reviews_refined.csv`
* `patents_refined.csv`
* `theses_refined.csv`
* `conferences_refined.csv`
* `unknown_refined.csv`
* `citations_refined.xlsx`

### What refinement does

* Detects conferences by container keywords like proceedings, conference, symposium, workshop, LNCS, ACM or IEEE proceedings
* Keeps real books and book-chapters as books
* Preserves reviews, patents, theses
* Stricter filters may remove some borderline high-impact citations

---

## Classification logic

### Primary (Level 1)

* Uses Crossref type when available
* Uses heuristics to detect reviews, surveys, theses, patents, books, and conferences
* Maximizes coverage (recall)

### Refinement (Level 2)

* Uses existing citing title and container text only
* Strong conference detection
* Produces `refined_class`
* More conservative (higher precision)

---

## Suggested workflows

* Start with single mode to save credits, then refine.
* For full analysis of your entire profile, run full mode then refine.
* Compare Level 1 and Level 2 results to balance false accepts and false rejects.
* Add Lens token if patent enrichment is required.

---

## Example session

```
$ python level1_graphical.py
Found 85 publications
Single mode: top paper has 135 citations
Export complete to scholar_outputs/

$ python level2_analysis.py
Reclassified 954 citing items
Books: 45 | Conferences: 117 | Reviews: 73 | Patents: 10 | Theses: 1 | Unknown: 15
Saved in scholar_outputs_refined/
```

---

## FAQ

Q: I ran out of SerpAPI credits.
A: Run `level2_analysis.py`. It uses your existing CSV and no API calls.

Q: My books count looks too high.
A: This is common when proceedings are published by Springer or IEEE. Refinement fixes this and adds a separate Conferences sheet.

Q: Can I analyze only one paper?
A: Yes. Choose Single mode.

Q: Where are files saved?
A: Level 1 saves to `scholar_outputs/`. Level 2 saves to `scholar_outputs_refined/`.

---

## Requirements

* Python ≥ 3.9
* pandas, networkx, requests, serpapi, openpyxl, tqdm, tkinter

---

## Credits

This tool was built to help researchers:

* Document high-impact reach through citations in books, reviews, and patents
* Support grant applications, tenure dossiers, and EB1A/EB1B petitions
* Explore citation networks visually

---

## License

MIT License — free to use, modify, and distribute with attribution.

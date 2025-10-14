import pandas as pd
import os

INPUT_FILE = "scholar_outputs/all_citations.csv"
OUTPUT_DIR = "scholar_outputs_refined"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def refine_classification(title: str, container: str, original_class: str) -> str:
    """Second-layer offline refinement of classification."""
    t = (title or "").lower()
    c = (container or "").lower()
    oc = (original_class or "").lower()

    # Explicit conference keywords
    conference_terms = [
        "proceedings", "conference", "symposium", "workshop",
        "colloquium", "annual meeting", "meeting", "ic", "acm", "ieee"
    ]
    # Book keywords (stricter than before)
    book_terms = ["book", "chapter", "handbook", "monograph", "volume"]

    # Patent
    if "patent" in t or "patent" in c or oc == "patent":
        return "patent"

    # Thesis
    if any(w in t or w in c for w in ["thesis", "dissertation", "phd", "masters"]) or oc == "thesis":
        return "thesis"

    # Review
    if any(w in t or w in c for w in ["review", "survey", "meta-analysis", "systematic review"]) or oc == "review":
        return "review"

    # Conference: if any conference term appears in container, or was previously marked book but looks like proceedings
    if any(w in c for w in conference_terms):
        return "conference"

    # Book: only if book keywords appear and not conference
    if any(w in t or w in c for w in book_terms):
        return "book"

    return "unknown"

def main():
    df = pd.read_csv(INPUT_FILE)
    if "final_class" not in df.columns:
        raise ValueError("Input CSV does not have 'final_class' column. Run the main script first.")

    df["refined_class"] = df.apply(
        lambda row: refine_classification(
            row.get("citing_title", ""),
            row.get("citing_container", ""),
            row.get("final_class", "")
        ),
        axis=1
    )

    # Create subsets
    df_review = df[df["refined_class"] == "review"]
    df_patent = df[df["refined_class"] == "patent"]
    df_book = df[df["refined_class"] == "book"]
    df_thesis = df[df["refined_class"] == "thesis"]
    df_conf = df[df["refined_class"] == "conference"]
    df_unknown = df[df["refined_class"] == "unknown"]

    # Save CSVs
    df.to_csv(os.path.join(OUTPUT_DIR, "all_citations_refined.csv"), index=False)
    df_review.to_csv(os.path.join(OUTPUT_DIR, "reviews_refined.csv"), index=False)
    df_patent.to_csv(os.path.join(OUTPUT_DIR, "patents_refined.csv"), index=False)
    df_book.to_csv(os.path.join(OUTPUT_DIR, "books_refined.csv"), index=False)
    df_thesis.to_csv(os.path.join(OUTPUT_DIR, "theses_refined.csv"), index=False)
    df_conf.to_csv(os.path.join(OUTPUT_DIR, "conferences_refined.csv"), index=False)
    df_unknown.to_csv(os.path.join(OUTPUT_DIR, "unknown_refined.csv"), index=False)

    # Save Excel
    xlsx_path = os.path.join(OUTPUT_DIR, "citations_refined.xlsx")
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name="All")
        df_review.to_excel(xw, index=False, sheet_name="Reviews")
        df_patent.to_excel(xw, index=False, sheet_name="Patents")
        df_book.to_excel(xw, index=False, sheet_name="Books")
        df_thesis.to_excel(xw, index=False, sheet_name="Theses")
        df_conf.to_excel(xw, index=False, sheet_name="Conferences")
        df_unknown.to_excel(xw, index=False, sheet_name="Unknown")

    print("Refinement complete:")
    print(f"  Total items: {len(df)}")
    print(f"  Reviews: {len(df_review)} | Patents: {len(df_patent)} | Books: {len(df_book)} | Theses: {len(df_thesis)} | Conferences: {len(df_conf)} | Unknown: {len(df_unknown)}")
    print(f"  Saved in {OUTPUT_DIR}")

if __name__ == "__main__":
    main()

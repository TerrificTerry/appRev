from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


DEFAULT_INPUT = Path("data/apple_review_collection/gui_runs")
DEFAULT_OUTPUT = Path("data/apple_review_collection/analysis")

TEXT_FIELDS = ["title", "review_text"]
EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001f5ff"
    "\U0001f600-\U0001f64f"
    "\U0001f680-\U0001f6ff"
    "\U0001f700-\U0001f77f"
    "\U0001f780-\U0001f7ff"
    "\U0001f800-\U0001f8ff"
    "\U0001f900-\U0001f9ff"
    "\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff"
    "\U00002700-\U000027bf"
    "\U00002600-\U000026ff"
    "]"
)


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "dataset"


def has_emoji(value: object) -> bool:
    return isinstance(value, str) and bool(EMOJI_RE.search(value))


def text_length(value: object) -> int:
    if not isinstance(value, str):
        return 0
    return len(value.strip())


def word_count(value: object) -> int:
    if not isinstance(value, str):
        return 0
    return len(re.findall(r"\b\w+\b", value))


def ascii_ratio(value: object) -> float:
    if not isinstance(value, str) or not value:
        return 0.0
    return sum(1 for char in value if ord(char) < 128) / len(value)


def is_low_signal(value: object) -> bool:
    if not isinstance(value, str):
        return True

    text = value.strip().lower()
    if not text:
        return True

    compact = re.sub(r"\s+", "", text)
    repeated_char = len(set(compact)) <= 2 and len(compact) >= 3
    short_generic = compact in {
        ".",
        "-",
        "good",
        "great",
        "bad",
        "nice",
        "ok",
        "okay",
        "loveit",
        "thanks",
        "thankyou",
        "👍",
        "👎",
    }
    return word_count(text) <= 2 or repeated_char or short_generic


def markdown_table(series: pd.Series, max_rows: int = 20) -> str:
    frame = series.head(max_rows).reset_index()
    frame.columns = [str(column) for column in frame.columns]
    return frame.to_markdown(index=False)


def describe_numeric(series: pd.Series) -> str:
    description = series.describe(percentiles=[0.25, 0.5, 0.75, 0.9, 0.95]).round(2)
    return description.to_frame(name=series.name).to_markdown()


def enrich_reviews(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for field in TEXT_FIELDS:
        if field not in df.columns:
            df[field] = ""

    df["review_text_length"] = df["review_text"].map(text_length)
    df["review_word_count"] = df["review_text"].map(word_count)
    df["title_length"] = df["title"].map(text_length)
    df["has_emoji"] = df["review_text"].map(has_emoji) | df["title"].map(has_emoji)
    df["ascii_ratio"] = df["review_text"].map(ascii_ratio)
    df["likely_non_english_or_mixed"] = df["ascii_ratio"] < 0.85
    df["low_signal_review_text"] = df["review_text"].map(is_low_signal)
    df["normalized_review_text"] = (
        df["review_text"]
        .fillna("")
        .str.lower()
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    return df


def save_bar(series: pd.Series, output_path: Path, title: str, xlabel: str, ylabel: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(8, 4.8))
    series.plot(kind="bar")
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.tight_layout()
    plt.savefig(output_path, dpi=160)
    plt.close()


def save_hist(series: pd.Series, output_path: Path, title: str, xlabel: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(8, 4.8))
    series.plot(kind="hist", bins=40)
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel("Review count")
    plt.tight_layout()
    plt.savefig(output_path, dpi=160)
    plt.close()


def save_graphs(df: pd.DataFrame, output_dir: Path, dataset_key: str) -> dict[str, Path]:
    graphs_dir = output_dir / "graphs" / dataset_key
    graph_paths = {
        "rating_distribution": graphs_dir / "rating_distribution.png",
        "review_length_distribution": graphs_dir / "review_length_distribution.png",
        "country_counts": graphs_dir / "country_counts.png",
        "missingness": graphs_dir / "missingness.png",
    }

    save_bar(
        df["rating"].value_counts(dropna=False).sort_index(),
        graph_paths["rating_distribution"],
        "Rating Distribution",
        "Rating",
        "Review count",
    )
    save_hist(
        df["review_text_length"],
        graph_paths["review_length_distribution"],
        "Review Length Distribution",
        "Characters in review_text",
    )
    save_bar(
        df["country"].value_counts().head(30),
        graph_paths["country_counts"],
        "Country Counts",
        "Country",
        "Review count",
    )
    save_bar(
        df.isna().mean().mul(100).sort_values(ascending=False),
        graph_paths["missingness"],
        "Missingness By Field",
        "Field",
        "Missing percent",
    )
    return graph_paths


def build_report(df: pd.DataFrame, dataset_name: str, graph_paths: dict[str, Path]) -> str:
    df = enrich_reviews(df)
    missingness = df.isna().mean().mul(100).round(2).sort_values(ascending=False)
    duplicate_review_ids = int(df["review_id"].duplicated().sum())
    duplicate_texts = int(
        df.loc[df["normalized_review_text"] != "", "normalized_review_text"]
        .duplicated()
        .sum()
    )
    repeated_texts = (
        df.loc[df["normalized_review_text"] != "", "normalized_review_text"]
        .value_counts()
        .loc[lambda counts: counts > 1]
    )

    app_name = df["app_name"].iloc[0] if "app_name" in df.columns and not df.empty else dataset_name
    sections = [
        f"# {app_name} Apple App Store Reviews EDA",
        "",
        "## Dataset Shape",
        "",
        f"- Source file: `{dataset_name}`",
        f"- Rows: {len(df)}",
        f"- Columns: {len(df.columns)}",
        f"- Countries: {df['country'].nunique() if 'country' in df.columns else 0}",
        f"- Review date range: {df['review_date'].min()} to {df['review_date'].max()}",
        "",
        "## Graphs",
        "",
        f"![Rating Distribution]({graph_paths['rating_distribution'].as_posix()})",
        "",
        f"![Review Length Distribution]({graph_paths['review_length_distribution'].as_posix()})",
        "",
        f"![Country Counts]({graph_paths['country_counts'].as_posix()})",
        "",
        f"![Missingness]({graph_paths['missingness'].as_posix()})",
        "",
        "## Rating Distribution",
        "",
        markdown_table(df["rating"].value_counts(dropna=False).sort_index()),
        "",
        "## Country Counts",
        "",
        markdown_table(df["country"].value_counts(), max_rows=50),
        "",
        "## Version Counts",
        "",
        markdown_table(df["version"].value_counts(dropna=False), max_rows=25),
        "",
        "## Review Length Distribution",
        "",
        describe_numeric(df["review_text_length"]),
        "",
        "## Review Word Count Distribution",
        "",
        describe_numeric(df["review_word_count"]),
        "",
        "## Missingness Percent By Field",
        "",
        missingness.to_frame("missing_percent").to_markdown(),
        "",
        "## Duplicate Signals",
        "",
        f"- Duplicate review_id rows: {duplicate_review_ids}",
        f"- Duplicate normalized review_text rows: {duplicate_texts}",
        "",
        "## Most Repeated Review Texts",
        "",
        markdown_table(repeated_texts, max_rows=20)
        if not repeated_texts.empty
        else "No repeated review text found.",
        "",
        "## Low-Signal / Language / Emoji Signals",
        "",
        f"- Low-signal review_text rows: {int(df['low_signal_review_text'].sum())}",
        f"- Reviews containing emoji in title or text: {int(df['has_emoji'].sum())}",
        f"- Low ASCII ratio rows, likely non-English or mixed-language: {int(df['likely_non_english_or_mixed'].sum())}",
        "",
        "## Shortest Review Examples",
        "",
        df.sort_values("review_text_length")
        .loc[:, ["country", "rating", "title", "review_text", "review_text_length"]]
        .head(15)
        .to_markdown(index=False),
        "",
        "## Structural / Data Quality Notes",
        "",
        "- Apple RSS is a recent-review feed, not a full historical archive.",
        "- Country should remain a first-class sampling dimension.",
        "- Low-signal and repeated-text rows should be tagged before deletion.",
        "- Add formal language detection before cross-country modeling.",
        "- Keep raw text unchanged; clean text can be added as a derived field later.",
    ]

    return "\n".join(sections)


def analyze_reviews_csv(input_path: Path, output_dir: Path) -> Path:
    df = pd.read_csv(input_path)
    df = enrich_reviews(df)
    dataset_key = slugify(input_path.stem)
    report_dir = output_dir / dataset_key
    graph_paths = save_graphs(df, report_dir, dataset_key)
    report_graph_paths = {
        key: Path("graphs") / dataset_key / path.name
        for key, path in graph_paths.items()
    }
    report = build_report(df, input_path.name, report_graph_paths)

    report_path = report_dir / f"{dataset_key}_eda_summary.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    return report_path


def find_review_csvs(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]

    per_app_csvs = sorted(input_path.glob("**/reviews_by_app/*_apple_reviews.csv"))
    if per_app_csvs:
        return per_app_csvs

    return sorted(input_path.glob("**/*apple*reviews*.csv"))


def analyze_path(input_path: Path, output_dir: Path) -> list[Path]:
    csv_paths = find_review_csvs(input_path)
    report_paths: list[Path] = []
    for csv_path in csv_paths:
        if "collection_summary" in csv_path.name:
            continue
        report_paths.append(analyze_reviews_csv(csv_path, output_dir))
    return report_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Run EDA on collected Apple review CSVs.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    report_paths = analyze_path(args.input, args.output_dir)

    print(f"Analyzed {len(report_paths)} CSV file(s)")
    for path in report_paths:
        print(f"Saved EDA report to {path}")


if __name__ == "__main__":
    main()

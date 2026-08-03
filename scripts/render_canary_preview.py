# ruff: noqa: E501
from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path
from typing import Any

from neveran_gazzetta.config import load_config
from neveran_gazzetta.domain.models import GazzettaArticle, GazzettaEditionSnapshot
from neveran_gazzetta.generation.names import (
    normalize_invented_person_name,
    replace_person_names,
    select_newsroom_bylines,
)

ROOT = Path(__file__).resolve().parents[1]


def _text(value: object | None) -> str:
    return escape(str(value or ""), quote=True)


def _article(article: GazzettaArticle, css_class: str = "") -> str:
    kicker = f'<p class="kicker">{_text(article.kicker)}</p>' if article.kicker else ""
    pull_quote = (
        f'<blockquote>“{_text(article.pull_quote)}”</blockquote>'
        if article.pull_quote
        else ""
    )
    paragraphs = "".join(f"<p>{_text(paragraph)}</p>" for paragraph in article.paragraphs)
    return f"""
      <article class="story {css_class}">
        {kicker}
        <p class="category">{_text(article.category)}</p>
        <h2>{_text(article.title)}</h2>
        <p class="byline">di {_text(article.byline)}</p>
        <p class="summary">{_text(article.summary)}</p>
        {paragraphs}
        {pull_quote}
      </article>
    """


def _replace_snapshot_strings(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        return replace_person_names(value, replacements)
    if isinstance(value, list):
        return [_replace_snapshot_strings(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_snapshot_strings(item, replacements)
            for key, item in value.items()
        }
    return value


def restyle_snapshot_with_current_name_policy(
    payload: dict[str, Any],
    *,
    newsroom_names: tuple[str, ...],
    per_edition: int,
) -> GazzettaEditionSnapshot:
    """Adatta un vecchio canary alla policy nomi corrente senza mutare il sorgente."""

    raw_snapshot = payload.get("snapshot")
    if not isinstance(raw_snapshot, dict):
        raise ValueError("Il canary non contiene uno snapshot di edizione")

    replacements: dict[str, str] = {}
    events = payload.get("events", [])
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("id", "legacy-event"))
            entities = event.get("entities", [])
            if not isinstance(entities, list):
                continue
            for index, entity in enumerate(entities):
                if not isinstance(entity, dict) or entity.get("invented") is not True:
                    continue
                original = entity.get("name")
                if not isinstance(original, str):
                    continue
                normalized, replaced = normalize_invented_person_name(
                    original,
                    seed=f"{event_id}:{index}",
                )
                if replaced is not None:
                    replacements[replaced] = normalized

    transformed = _replace_snapshot_strings(raw_snapshot, replacements)
    issue_number = int(transformed["issueNumber"])
    bylines = select_newsroom_bylines(issue_number, newsroom_names, per_edition)
    articles = [transformed["leadArticle"], *transformed["articles"]]
    for index, article in enumerate(articles):
        article["byline"] = bylines[index % len(bylines)]

    return GazzettaEditionSnapshot.model_validate(transformed)


def render_preview(payload: dict[str, Any]) -> str:
    raw_snapshot = payload.get("snapshot")
    if not isinstance(raw_snapshot, dict):
        raise ValueError("Il canary non contiene uno snapshot di edizione")
    edition = GazzettaEditionSnapshot.model_validate(raw_snapshot)

    publication_date = edition.publication_date.astimezone().strftime("%d/%m/%Y · %H:%M")
    major = [article for article in edition.articles if article.importance == "major"]
    minor = [article for article in edition.articles if article.importance == "minor"]
    brief = next(article for article in edition.articles if article.importance == "brief")

    breaking = "".join(f"<li>{_text(item)}</li>" for item in edition.breaking_news)
    major_html = "".join(_article(article, "major") for article in major)
    minor_html = "".join(_article(article, "minor") for article in minor)

    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Gazzetta di Neveran · Edizione {edition.issue_number}</title>
  <style>
    :root {{ color-scheme: light; --ink:#17130f; --paper:#eee5ce; --red:#7b211b; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:#2b2926; color:var(--ink); font-family:Georgia,'Times New Roman',serif; }}
    main {{ width:min(1180px,96vw); margin:24px auto; padding:28px 38px 44px; background:var(--paper); box-shadow:0 12px 48px #0008; }}
    header {{ text-align:center; border-block:5px double var(--ink); padding:16px 0 12px; }}
    h1 {{ margin:0; font-size:clamp(3rem,8vw,6.8rem); line-height:.84; letter-spacing:-.055em; text-transform:uppercase; }}
    .subtitle {{ margin:12px 0 6px; font-style:italic; font-size:1.15rem; }}
    .dateline {{ display:flex; justify-content:space-between; gap:16px; margin-top:12px; padding-top:8px; border-top:1px solid; font:bold .78rem Arial,sans-serif; text-transform:uppercase; letter-spacing:.08em; }}
    .breaking {{ margin:18px 0; padding:10px 14px; border-block:2px solid var(--red); list-style:none; display:grid; grid-template-columns:repeat(3,1fr); gap:14px; color:var(--red); font-weight:bold; }}
    .breaking li+li {{ border-left:1px solid var(--red); padding-left:14px; }}
    .lead {{ padding:18px 0 22px; border-bottom:3px double; }}
    .lead h2 {{ font-size:clamp(2.3rem,5vw,4.7rem); line-height:.96; }}
    .lead .summary {{ font-size:1.3rem; }}
    .grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 28px; }}
    .story {{ padding:20px 0; border-bottom:1px solid #776e5d; }}
    .grid .story:nth-child(even) {{ border-left:1px solid #776e5d; padding-left:28px; }}
    h2 {{ margin:.2rem 0 .35rem; font-size:2rem; line-height:1.02; }}
    p {{ line-height:1.45; }}
    .category,.kicker,.byline {{ margin:.2rem 0; font-family:Arial,sans-serif; text-transform:uppercase; letter-spacing:.08em; }}
    .category {{ color:var(--red); font-size:.72rem; font-weight:800; }}
    .kicker {{ font-size:.72rem; }}
    .byline {{ font-size:.68rem; }}
    .summary {{ font-weight:bold; }}
    blockquote {{ margin:18px 8%; padding:12px 18px; border-left:4px solid var(--red); color:var(--red); font-size:1.2rem; font-style:italic; }}
    .brief {{ margin-top:22px; padding:18px 22px; border:2px solid; }}
    footer {{ margin-top:26px; text-align:center; border-top:4px double; padding-top:18px; }}
    footer q {{ display:block; font-size:1.3rem; font-style:italic; }}
    footer p {{ font:bold .75rem Arial,sans-serif; text-transform:uppercase; letter-spacing:.12em; }}
    .notice {{ position:sticky; top:0; z-index:2; margin:-28px -38px 20px; padding:8px; background:#17130f; color:#f5e9c9; text-align:center; font:700 .72rem Arial,sans-serif; letter-spacing:.1em; text-transform:uppercase; }}
    @media (max-width:720px) {{
      main {{ margin:0; width:100%; padding:20px; }} .notice {{ margin:-20px -20px 16px; }}
      .breaking,.grid {{ grid-template-columns:1fr; }}
      .breaking li+li,.grid .story:nth-child(even) {{ border-left:0; padding-left:0; }}
      .breaking li+li {{ border-top:1px solid var(--red); padding-top:10px; }}
      .dateline {{ flex-direction:column; }}
    }}
  </style>
</head>
<body>
  <main>
    <div class="notice">Anteprima locale · dry-run · non pubblicata</div>
    <header>
      <h1>Gazzetta di Neveran</h1>
      <p class="subtitle">{_text(edition.masthead_subtitle)}</p>
      <div class="dateline"><span>{_text(edition.location_label)}</span><span>Edizione {edition.issue_number}</span><time>{publication_date}</time></div>
    </header>
    <ol class="breaking">{breaking}</ol>
    {_article(edition.lead_article, "lead")}
    <section class="grid">{major_html}</section>
    <section class="grid">{minor_html}</section>
    {_article(brief, "brief")}
    <footer><q>{_text(edition.editorial_quote)}</q><p>{_text(edition.closing_motto)}</p></footer>
  </main>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Renderizza uno snapshot canary in HTML locale")
    parser.add_argument("input", type=Path, help="JSON prodotto da gazzetta-canary")
    parser.add_argument("--output", type=Path, help="Destinazione HTML")
    parser.add_argument(
        "--snapshot-output",
        type=Path,
        help="Copia validata per la route di preview della Main App",
    )
    parser.add_argument(
        "--apply-current-name-policy",
        action="store_true",
        help="Applica soltanto all'anteprima la policy nomi Neveran corrente",
    )
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    snapshot = GazzettaEditionSnapshot.model_validate(payload.get("snapshot"))
    if args.apply_current_name_policy:
        config = load_config(ROOT, environment={"ENVIRONMENT": "test"})
        recurring = config.editorial.recurring_entities
        snapshot = restyle_snapshot_with_current_name_policy(
            payload,
            newsroom_names=recurring.journalist_core_names,
            per_edition=recurring.journalist_core_per_edition,
        )
        payload = {**payload, "snapshot": snapshot.model_dump(mode="json", by_alias=True)}

    output = args.output or args.input.with_suffix(".html")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_preview(payload), encoding="utf-8")
    print(output.resolve())
    if args.snapshot_output:
        args.snapshot_output.parent.mkdir(parents=True, exist_ok=True)
        args.snapshot_output.write_text(
            snapshot.model_dump_json(by_alias=True, indent=2),
            encoding="utf-8",
        )
        print(args.snapshot_output.resolve())
    if args.apply_current_name_policy:
        print("Policy nomi corrente applicata solo agli output di anteprima; canary intatto.")


if __name__ == "__main__":
    main()

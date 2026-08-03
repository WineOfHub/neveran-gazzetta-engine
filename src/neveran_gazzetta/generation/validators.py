from __future__ import annotations

import re
import unicodedata

from neveran_gazzetta.config import EditorialPolicy
from neveran_gazzetta.domain.models import (
    GazzettaArticle,
    GazzettaEditionSnapshot,
    ValidationIssue,
    ValidationReport,
)
from neveran_gazzetta.generation.guardrails import validate_loop_usage

_WORD = re.compile(r"[^\W\d_]+(?:['\u2019][^\W\d_]+)?", re.UNICODE)
_FORBIDDEN_TEXT = re.compile(
    r"\b(lorem ipsum|placeholder|system prompt|chunk[_ -]?id|citation[_ -]?id)\b",
    re.IGNORECASE,
)
_HTML = re.compile(r"<\/?[a-z][^>]*>", re.IGNORECASE)


def word_count(text: str) -> int:
    normalized = unicodedata.normalize("NFC", text)
    return len(_WORD.findall(normalized))


def truncate_to_word_limit(text: str, max_words: int) -> str:
    normalized = unicodedata.normalize("NFC", text).strip()
    words = list(_WORD.finditer(normalized))
    if len(words) <= max_words:
        return normalized
    truncated = normalized[: words[max_words - 1].end()].rstrip(" ,;:—-")
    return truncated if truncated.endswith((".", "!", "?", "…")) else f"{truncated}."


def _issue(code: str, message: str, path: str, *, repairable: bool = True) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, path=path, repairable=repairable)


def _validate_article(
    article: GazzettaArticle,
    policy: EditorialPolicy,
    *,
    path: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    budget = getattr(policy.slot_budgets, article.importance.value)
    if len(article.title) > budget.title_max_characters:
        issues.append(_issue("title_too_long", "Titolo oltre budget", f"{path}.title"))
    if word_count(article.summary) > budget.summary_max_words:
        issues.append(_issue("summary_too_long", "Sommario oltre budget", f"{path}.summary"))
    if len(article.paragraphs) != budget.paragraph_count:
        issues.append(
            _issue("paragraph_count", "Numero paragrafi errato", f"{path}.paragraphs")
        )
    for index, paragraph in enumerate(article.paragraphs):
        words = word_count(paragraph)
        if not budget.paragraph_min_words <= words <= budget.paragraph_max_words:
            issues.append(
                _issue(
                    "paragraph_budget",
                    "Paragrafo fuori budget parole",
                    f"{path}.paragraphs.{index}",
                )
            )
    if (
        article.pull_quote
        and budget.pull_quote_max_words is not None
        and word_count(article.pull_quote) > budget.pull_quote_max_words
    ):
        issues.append(
            _issue("pull_quote_too_long", "Pull quote oltre budget", f"{path}.pullQuote")
        )
    for field_path, text in (
        ("byline", article.byline),
        ("title", article.title),
        ("summary", article.summary),
        *((f"paragraphs.{index}", value) for index, value in enumerate(article.paragraphs)),
    ):
        if _FORBIDDEN_TEXT.search(text) or _HTML.search(text):
            issues.append(
                _issue("forbidden_text", "Testo tecnico o placeholder", f"{path}.{field_path}")
            )
        loop_issue = validate_loop_usage(text)
        if loop_issue:
            issues.append(loop_issue.model_copy(update={"path": f"{path}.{field_path}"}))
    return issues


def validate_edition(
    edition: GazzettaEditionSnapshot,
    policy: EditorialPolicy,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    for index, item in enumerate(edition.breaking_news):
        if len(item) > policy.slot_budgets.breaking.max_characters:
            issues.append(
                _issue("breaking_too_long", "Ultim'ora oltre budget", f"breakingNews.{index}")
            )
        if _FORBIDDEN_TEXT.search(item) or _HTML.search(item):
            issues.append(
                _issue("forbidden_text", "Testo tecnico o placeholder", f"breakingNews.{index}")
            )
        loop_issue = validate_loop_usage(item)
        if loop_issue:
            issues.append(loop_issue.model_copy(update={"path": f"breakingNews.{index}"}))

    issues.extend(_validate_article(edition.lead_article, policy, path="leadArticle"))
    for index, article in enumerate(edition.articles):
        issues.extend(_validate_article(article, policy, path=f"articles.{index}"))
    distinct_bylines = {
        article.byline.casefold().strip()
        for article in (edition.lead_article, *edition.articles)
    }
    if not 3 <= len(distinct_bylines) <= 5:
        issues.append(
            _issue(
                "byline_rotation",
                "La prima pagina richiede da tre a cinque firme distinte",
                "articles",
            )
        )
    if word_count(edition.editorial_quote) > policy.slot_budgets.editorial_quote.max_words:
        issues.append(_issue("quote_too_long", "Citazione oltre budget", "editorialQuote"))
    if word_count(edition.closing_motto) > policy.slot_budgets.closing_motto.max_words:
        issues.append(_issue("motto_too_long", "Motto oltre budget", "closingMotto"))
    all_text = " ".join(
        [edition.editorial_quote, edition.closing_motto, edition.masthead_subtitle]
    )
    if _FORBIDDEN_TEXT.search(all_text) or _HTML.search(all_text):
        issues.append(_issue("forbidden_text", "Testo tecnico o placeholder", "edition"))
    loop_issue = validate_loop_usage(all_text)
    if loop_issue:
        issues.append(loop_issue.model_copy(update={"path": "edition"}))
    return ValidationReport(passed=not issues, issues=tuple(issues))

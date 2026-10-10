"""Validation of the narrative.

Structural checks (both modes):
  - strict schema (no extra fields), required fields, length and count limits;
  - every evidence ID exists in the packet;
  - every point in a section cites at least one of that section's anchors;
  - every anchor of a section is cited in that section (no evidence lost), and
    a section with no anchors must be empty (nothing invented);
  - the overview cites "recommendation".

Extra checks for model text only (mode="llm"):
  - no digits: figures are shown from the backend, never from model prose;
  - no banned phrases (price targets, guarantees, expected returns, news, trade instructions);
  - no recommendation token (BUY/HOLD/SELL) other than the engine's;
  - no synthetic/demo wording when the provenance is not synthetic;
  - written in the requested language (stop-word heuristic).

These checks bound and audit the output. They do not prove that every sentence
is true: a valid, well-referenced sentence can still mischaracterize evidence.
"""

import json
import re

from pydantic import ValidationError

from app.narration.config import MAX_RAW_OUTPUT_CHARS
from app.narration.evidence import OUTPUT_SECTIONS, all_ids, anchors
from app.narration.models import EvidencePacket, NarrativeReport


class InvalidNarrativeError(ValueError):
    """Internal detail is kept here; it is never returned to API clients."""


BANNED_PHRASES = (
    # en
    "price target", "target price", "guarantee", "expected return", "will rise",
    "will fall", "news", "buy now", "sell now", "place an order",
    # es
    "precio objetivo", "garantiz", "rentabilidad esperada", "subirá", "bajará",
    "noticia", "compra ahora", "vende ahora", "compre ahora", "venda ahora",
)
_STOPWORDS = {
    "es": {"el", "la", "los", "las", "de", "del", "que", "y", "es", "en", "una", "un",
           "por", "con", "se", "para", "son", "está", "como", "pero", "su", "sus"},
    "en": {"the", "is", "and", "of", "to", "in", "with", "are", "for", "this", "that",
           "on", "its", "but", "as", "by", "an", "be"},
}
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def parse_model_content(content: str) -> dict:
    if len(content) > MAX_RAW_OUTPUT_CHARS:
        raise InvalidNarrativeError("model output too long")
    text = content.strip()
    match = _FENCE.match(text)
    if match:
        text = match.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise InvalidNarrativeError("model output is not valid JSON") from error
    if not isinstance(data, dict):
        raise InvalidNarrativeError("model output is not a JSON object")
    return data


def _points(report: NarrativeReport):
    yield "overview", report.overview
    for section in OUTPUT_SECTIONS:
        for point in getattr(report, section):
            yield section, point


def _check_structure(report: NarrativeReport, packet: EvidencePacket) -> None:
    known = all_ids(packet)
    for section, point in _points(report):
        unknown = [i for i in point.evidenceIds if i not in known]
        if unknown:
            raise InvalidNarrativeError(f"unknown evidence ids in {section}: {unknown}")
        if len(set(point.evidenceIds)) != len(point.evidenceIds):
            raise InvalidNarrativeError(f"duplicate evidence ids in {section}")

    if "recommendation" not in report.overview.evidenceIds:
        raise InvalidNarrativeError("overview must cite 'recommendation'")

    for section, required in anchors(packet).items():
        points = getattr(report, section)
        if not required and points:
            raise InvalidNarrativeError(f"{section} must be empty: no evidence for it")
        cited: set[str] = set()
        for point in points:
            hits = set(point.evidenceIds) & set(required)
            if not hits:
                raise InvalidNarrativeError(f"a point in {section} cites none of its evidence")
            misplaced = set(point.evidenceIds) - set(required)
            if misplaced:
                raise InvalidNarrativeError(f"a point in {section} cites evidence outside its section: {sorted(misplaced)}")
            cited |= hits
        missing = [i for i in required if i not in cited]
        if missing:
            raise InvalidNarrativeError(f"{section} omits evidence: {missing}")


def _language_ok(text: str, language: str) -> bool:
    words = re.findall(r"[a-záéíóúñü]+", text.lower())
    target = sum(1 for w in words if w in _STOPWORDS[language])
    other_language = "en" if language == "es" else "es"
    other = sum(1 for w in words if w in _STOPWORDS[other_language])
    return target >= 3 and target >= 2 * other


def _check_model_text(report: NarrativeReport, packet: EvidencePacket, language: str) -> None:
    texts = [report.title] + [point.text for _, point in _points(report)]
    joined = " ".join(texts)
    lowered = joined.lower()

    if re.search(r"\d", joined):
        raise InvalidNarrativeError("model text contains digits")
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            raise InvalidNarrativeError(f"banned phrase: {phrase}")
    for token in re.findall(r"\b(BUY|HOLD|SELL)\b", joined):
        if token != packet.recommendation:
            raise InvalidNarrativeError("text names a recommendation the engine did not emit")
    if packet.provenance != "synthetic" and re.search(r"synthetic|sintétic|sintetic|\bdemo", lowered):
        raise InvalidNarrativeError("text claims synthetic data for non-synthetic provenance")
    if not _language_ok(joined, language):
        raise InvalidNarrativeError("text is not in the requested language")


def validate_narrative(data: dict, packet: EvidencePacket, language: str, mode: str = "llm") -> NarrativeReport:
    try:
        report = NarrativeReport.model_validate(data)
    except ValidationError as error:
        raise InvalidNarrativeError("model output does not match the schema") from error
    _check_structure(report, packet)
    if mode == "llm":
        _check_model_text(report, packet, language)
    return report

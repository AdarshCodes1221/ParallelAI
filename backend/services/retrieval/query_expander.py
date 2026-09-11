"""
Lightweight query understanding for RAG retrieval.

The goal is that *natural* user wording — abbreviations, shorthand,
typos, or paraphrases — retrieves the same evidence chunks regardless
of formulation.

Pipeline implemented here:

    query
      → lightweight normalisation  (always; no LLM)
      → Ollama query expansion     (ONLY when ``should_expand`` says so)
      → list of search variants

The caller (``RAGService.search_results``) then searches Redis with every
variant and fuses the hits via best-rank RRF.

Design constraints honoured:
  * No large synonym dictionary — abbreviation table is ≤ 20 entries.
  * Ollama expansion produces **retrieval terms**, never answers.
  * Expansion is gated by a heuristic so it never fires on rich queries.
  * All Ollama calls fail soft to an empty variant list.
"""

import json
import logging
import re
import urllib.error
import urllib.request

from core.config import get_settings

logger = logging.getLogger(__name__)


# ── 1. Small abbreviation / typo tables (NOT a thesaurus) ────────────────

# Common document-Q&A shorthand.  Keys are lowercase, punctuation-free.
# Values are the canonical expanded form.
_ABBREVIATIONS: dict[str, str] = {
    # shorthand seen in test cases / real prompts
    "bld": "blood",
    "grp": "group",
    "db": "database",
    # professional abbreviations
    "cfg": "config",
    "mgr": "manager",
    "dept": "department",
    "addr": "address",
    "edu": "education",
    "inst": "institute",
    "dev": "development",
    "qa": "quality assurance",
    "ui": "user interface",
    "ux": "user experience",
}

# A handful of very common misspellings.
_TYPOS: dict[str, str] = {
    "teh": "the",
    "adn": "and",
    "recieve": "receive",
    "seperate": "separate",
    "occured": "occurred",
    "untill": "until",
}

# Retrieval aliases are deliberately small and scoped to common resume/profile
# fields. They broaden lexical matching without turning every query into an
# LLM expansion request.
_RETRIEVAL_ALIASES: dict[str, tuple[str, ...]] = {
    "blood group": ("blood type",),
    "blood type": ("blood group",),
    "phone": ("mobile", "contact number"),
    "mobile": ("phone", "contact number"),
    "contact number": ("phone", "mobile"),
    "email": ("mail",),
    "mail": ("email",),
    "cgpa": ("gpa", "grade point average"),
    "gpa": ("cgpa", "grade point average"),
    "projects": ("work done",),
    "work done": ("projects",),
    "frontend": ("ui", "user interface"),
    "ui": ("frontend", "user interface"),
    "framework": ("frontend",),
    "database": ("datastore",),
    "db": ("database", "datastore"),
    "datastore": ("database",),
}

# Stop-words reused from RAGService._search (plus question/function words).
_STOP_WORDS: frozenset[str] = frozenset({
    "what", "is", "are", "the", "a", "an", "in", "on", "of", "for", "to",
    "and", "or", "tell", "me", "about", "give", "show", "from", "this",
    "that", "his", "her", "their", "my", "which", "who", "where", "when",
    "why", "how", "has", "have", "had", "did", "do", "done", "i", "you",
    "can", "could", "would", "should", "will", "with", "as", "at", "by",
})


# ── 2. Normalisation (always-on, zero LLM cost) ──────────────────────────

def normalize(query: str) -> str:
    """Expand abbreviations and fix common typos.

    Preserves word order, lowercases, and leaves unknown tokens untouched
    (including punctuation such as trailing ``?``).
    """
    text = query.lower().strip()
    if not text:
        return text
    tokens = text.split()
    out: list[str] = []
    for token in tokens:
        clean = re.sub(r"[^\w]", "", token)
        if clean in _ABBREVIATIONS:
            out.append(_ABBREVIATIONS[clean])
        elif clean in _TYPOS:
            out.append(_TYPOS[clean])
        else:
            out.append(token)
    return " ".join(out)


def meaningful_terms(query: str) -> list[str]:
    """Return content-bearing tokens (stop-words and 1-char tokens removed)."""
    tokens = re.findall(r"[a-z0-9]+", query.lower())
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


def retrieval_terms(query: str) -> list[str]:
    """Return meaningful terms plus a small deterministic alias set."""
    terms = meaningful_terms(normalize(query))
    text = normalize(query)
    seen = set(terms)
    for phrase, aliases in _RETRIEVAL_ALIASES.items():
        if re.search(rf"\b{re.escape(phrase)}\b", text):
            for alias in aliases:
                for term in meaningful_terms(alias):
                    if term not in seen:
                        terms.append(term)
                        seen.add(term)
    return terms


def should_expand(query: str, normalized: str) -> bool:
    """Heuristic: is an Ollama expansion call worthwhile?

    Returns ``True`` when the query carries too little signal for
    reliable retrieval:
      * ≤ 3 meaningful content terms (shorthand / abbreviation territory)
      * 4 terms AND the query is a question with short-form tokens

    Returns ``False`` for rich queries (≥ 5 meaningful terms) so we skip
    the LLM call entirely.
    """
    terms = meaningful_terms(normalized)
    if not terms:
        return False
    if len(terms) <= 3:
        return True
    if len(terms) >= 5:
        return False
    # 4 meaningful terms — expand only for question patterns with shorthand
    is_question = bool(re.match(
        r"^(what|which|who|where|when|why|how|tell|give|show|name|list|find|describe)\b",
        normalized.strip(), re.IGNORECASE,
    ))
    has_short = any(len(t) <= 3 for t in terms)
    return is_question and has_short


# ── 3. Ollama-based expansion (retrieval terms, NOT answers) ─────────────

_EXPANSION_PROMPT = """You are a query expansion system for document search.
Given the user's search query, produce 1-3 ALTERNATIVE phrasings or keyword
combinations that would retrieve the same document content.

These are retrieval terms ONLY — do NOT answer the question, do NOT explain.
Output each alternative on its own line, max 6 words per line.

Original: {query}
Normalized: {normalized}

Alternatives:"""


def _ollama_generate(
    prompt: str,
    ollama_url: str,
    model: str,
    timeout: int = 15,
) -> str | None:
    """Single-turn Ollama ``/api/generate`` call.  Returns ``None`` on failure."""
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{ollama_url}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as exc:
        logger.debug("Ollama expansion call failed: %s", exc)
        return None
    return data.get("response", "")


def _parse_expansion(response: str) -> list[str]:
    """Parse Ollama response into a clean list of search phrases."""
    if not response:
        return []
    alternatives: list[str] = []
    seen: set[str] = set()
    for line in response.splitlines():
        line = line.strip()
        # skip empty / list markers / meta-commentary
        if not line:
            continue
        if line[0] in "-*•" or re.match(r"^\d+[.)]\s*", line):
            # Strip the list marker: -, *, •, or digits optionally followed by
            # . or ), then any trailing whitespace.  The old regex required a
            # literal ")" so it never matched "-" or "1." forms.
            line = re.sub(r"^[-*•\d]+[.)\s]*", "", line).strip()
        # skip lines that look like explanations or answers
        if line.lower().startswith(("note:", "the ", "answer:", "i would")):
            continue
        # take only the first phrase (up to first sentence-ending punctuation)
        line = re.split(r"[.!?]", line)[0].strip()
        if not line:
            continue
        if len(line.split()) > 8:
            continue  # too sentence-like; probably an answer
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        alternatives.append(line)
    return alternatives[:3]


def expand_with_ollama(
    query: str,
    normalized: str,
    ollama_url: str | None = None,
    model: str | None = None,
) -> list[str]:
    """Ask Ollama for alternative retrieval phrasings.

    Returns up to 3 alternative search strings (never the original or
    normalized forms).  Empty list on any failure.
    """
    if not ollama_url:
        return []

    settings = get_settings()
    model = model or settings.ollama_llm_model

    prompt = _EXPANSION_PROMPT.format(query=query, normalized=normalized)
    response = _ollama_generate(prompt, ollama_url, model)
    if not response:
        return []

    return _parse_expansion(response)


# ── 4. Public API: assemble the full variant list ────────────────────────

def generate_variants(
    query: str,
    ollama_url: str | None = None,
    model: str | None = None,
) -> list[str]:
    """Produce the complete list of query variants for multi-query retrieval.

    Order:
      1. original query
      2. normalised (if different from original)
      3. Ollama-expanded alternatives (only when ``should_expand`` fires
         and ``query_expansion_enabled`` is true in settings)

    Always returns at least one element (the original query).
    """
    variants: list[str] = [query]
    normalized = normalize(query)
    if normalized and normalized != query.lower().strip():
        variants.append(normalized)

    settings = get_settings()
    if not settings.query_expansion_enabled:
        return variants

    if should_expand(query, normalized) and ollama_url:
        expanded = expand_with_ollama(query, normalized, ollama_url, model)
        existing = {v.lower().strip() for v in variants}
        for alt in expanded:
            if alt.lower().strip() not in existing:
                variants.append(alt)
                existing.add(alt.lower().strip())

    return variants

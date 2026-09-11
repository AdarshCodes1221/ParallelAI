#!/usr/bin/env python3
"""
Unit tests for services/retrieval/query_expander.py — QueryExpander.

All Ollama HTTP calls are mocked (never hit the network).  Tests cover:

  * Normalisation (abbreviation / typo expansion)
  * Meaningful-term extraction (stop-word stripping)
  * Expansion gating heuristic (should_expand)
  * Ollama expansion parsing & failure modes
  * Full generate_variants() pipeline
  * Spec query-variation coverage:
      blood group / bld grp / blood type
      email / mail
      phone / mobile / contact number
      CGPA / GPA
      projects / work done
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure backend root is on sys.path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from services.retrieval import query_expander
from services.retrieval.query_expander import (
    _parse_expansion,
    _ABBREVIATIONS,
    _TYPOS,
    expand_with_ollama,
    generate_variants,
    meaningful_terms,
    normalize,
    retrieval_terms,
    should_expand,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

OLLAMA_URL = "http://mocked-ollama:11434"
MODEL = "llama3.2:3b"


def _patch_ollama(response_text=None):
    """Patch _ollama_generate to return the given text (or None to simulate failure)."""
    return patch(
        "services.retrieval.query_expander._ollama_generate",
        return_value=response_text,
    )


# ── 1. Normalisation ─────────────────────────────────────────────────────────

class TestNormalize:
    def test_expands_known_abbreviations(self):
        assert normalize("bld grp") == "blood group"
        assert normalize("db") == "database"
        assert normalize("cfg") == "config"
        assert normalize("mgr") == "manager"
        assert normalize("dept") == "department"
        assert normalize("addr") == "address"

    def test_expands_compound_abbrev_query(self):
        # "bld grp" → "blood group"
        result = normalize("bld grp")
        assert "blood" in result
        assert "group" in result

    def test_fixes_typos(self):
        assert normalize("teh cat") == "the cat"
        assert normalize("seperate") == "separate"
        assert normalize("recieve") == "receive"

    def test_preserves_unknown_tokens(self):
        result = normalize("what is my email address")
        assert "email" in result
        assert "address" in result
        # stop-words are NOT removed by normalize (only abbreviations/typos expanded)
        assert "what" in result

    def test_lowercases(self):
        assert normalize("BLOOD GROUP") == "blood group"
        assert normalize("CGPA") == "cgpa"
        assert normalize("GPA") == "gpa"

    def test_empty_string(self):
        assert normalize("") == ""
        assert normalize("   ") == ""

    def test_preserves_punctuation_on_unknown(self):
        result = normalize("cgpa?")
        assert "cgpa" in result

    def test_mixed_known_and_unknown(self):
        result = normalize("bld grp and contact number")
        assert "blood" in result
        assert "group" in result
        assert "contact" in result
        assert "number" in result

    def test_all_abbreviations_in_table(self):
        """Every key in _ABBREVIATIONS should map to a value with >= 2 words or different form."""
        for abbr, expansion in _ABBREVIATIONS.items():
            assert abbr != expansion, f"{abbr} maps to itself"
            assert isinstance(abbr, str) and isinstance(expansion, str)
            assert len(abbr) >= 2, f"abbreviation '{abbr}' too short to be useful"

    def test_all_typos_in_table(self):
        for typo, correction in _TYPOS.items():
            assert typo != correction, f"{typo} maps to itself"
            assert len(typo) >= 3, f"typo '{typo}' too short to be distinctive"


# ── 2. Meaningful terms ──────────────────────────────────────────────────────

class TestMeaningfulTerms:
    def test_removes_stop_words(self):
        terms = meaningful_terms("what is my blood group")
        assert "blood" in terms
        assert "group" in terms
        assert "what" not in terms
        assert "is" not in terms
        assert "my" not in terms

    def test_extracts_single_term_queries(self):
        assert meaningful_terms("email") == ["email"]
        assert meaningful_terms("phone") == ["phone"]
        assert meaningful_terms("projects") == ["projects"]

    def test_removes_single_char_tokens(self):
        terms = meaningful_terms("a b c")
        assert terms == []

    def test_cgpa_and_gpa(self):
        assert meaningful_terms("CGPA") == ["cgpa"]
        assert meaningful_terms("GPA") == ["gpa"]

    def test_two_term_queries(self):
        terms = meaningful_terms("contact number")
        assert terms == ["contact", "number"]
        terms = meaningful_terms("blood type")
        assert terms == ["blood", "type"]

    def test_empty_query(self):
        assert meaningful_terms("") == []

    def test_strips_punctuation(self):
        terms = meaningful_terms("email?")
        assert terms == ["email"]
        terms = meaningful_terms("phone-number")
        assert terms == ["phone", "number"]

    def test_retrieval_terms_cover_requested_field_aliases(self):
        assert {"blood", "type"}.issubset(retrieval_terms("blood group"))
        assert "mobile" in retrieval_terms("phone")
        assert "mail" in retrieval_terms("email")
        assert "gpa" in retrieval_terms("CGPA")
        assert "projects" in retrieval_terms("work done")
        assert "ui" in retrieval_terms("frontend")
        assert "datastore" in retrieval_terms("database")


# ── 3. should_expand heuristic ───────────────────────────────────────────────

class TestShouldExpand:
    def test_short_query_triggers_expansion(self):
        assert should_expand("email", normalize("email")) is True
        assert should_expand("phone", normalize("phone")) is True
        assert should_expand("projects", normalize("projects")) is True
        assert should_expand("CGPA", normalize("CGPA")) is True

    def test_two_term_query_triggers_expansion(self):
        assert should_expand("blood group", normalize("blood group")) is True
        assert should_expand("bld grp", normalize("bld grp")) is True

    def test_three_term_query_triggers_expansion(self):
        assert should_expand("contact number details", normalize("contact number details")) is True

    def test_rich_query_does_not_trigger(self):
        long_query = "what are the key differences between supervised and unsupervised learning algorithms in machine learning"
        assert should_expand(long_query, normalize(long_query)) is False

    def test_five_terms_never_expands(self):
        query = "machine learning model training process overview"
        assert should_expand(query, normalize(query)) is False

    def test_four_terms_question_with_short_token_expands(self):
        # 4 terms, is a question, has a short token (<=3 chars)
        query = "what is my cgpa score"
        assert should_expand(query, normalize(query)) is True

    def test_four_terms_not_question_does_not_expand(self):
        # 4 terms, no short tokens, not a question
        query = "database administration best practices guide"
        normalized = normalize(query)
        # 4 meaningful terms, no short tokens → False
        assert should_expand(query, normalized) is False

    def test_empty_terms_returns_false(self):
        assert should_expand("", "") is False
        assert should_expand("the a an", normalize("the a an")) is False


# ── 4. Ollama expansion (mocked) ─────────────────────────────────────────────

class TestExpandWithOllama:
    @patch("services.retrieval.query_expander._ollama_generate", return_value=None)
    def test_failure_returns_empty_list(self, _mock):
        result = expand_with_ollama("bld grp", "blood group", OLLAMA_URL, MODEL)
        assert result == []
        _mock.assert_called_once()

    @patch("services.retrieval.query_expander._ollama_generate", return_value="")
    def test_empty_response_returns_empty(self, _mock):
        result = expand_with_ollama("email", "email", OLLAMA_URL, MODEL)
        assert result == []

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="blood type\nblood group type\npatient blood group")
    def test_parses_multiline_response(self, _mock):
        result = expand_with_ollama("bld grp", "blood group", OLLAMA_URL, MODEL)
        assert result == ["blood type", "blood group type", "patient blood group"]
        assert len(result) <= 3

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="email address\ncontact email\nmail address")
    def test_email_variants(self, _mock):
        result = expand_with_ollama("email", "email", OLLAMA_URL, MODEL)
        assert "email address" in result
        assert "mail address" in result

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="mobile phone\ncontact number\ntelephone")
    def test_phone_variants(self, _mock):
        result = expand_with_ollama("phone", "phone", OLLAMA_URL, MODEL)
        assert "mobile phone" in result
        assert "contact number" in result

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="GPA\ncumulative grade\ngrade point average")
    def test_cgpa_variants(self, _mock):
        result = expand_with_ollama("CGPA", "cgpa", OLLAMA_URL, MODEL)
        assert "GPA" in result
        assert "cumulative grade" in result

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="work projects\nprofessional experience\nproject portfolio")
    def test_projects_variants(self, _mock):
        result = expand_with_ollama("projects", "projects", OLLAMA_URL, MODEL)
        assert "work projects" in result
        assert "professional experience" in result

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="Note: Here are the alternatives.\n1. blood type\n2. blood group type\n3. patient blood")
    def test_strips_meta_commentary(self, _mock):
        result = expand_with_ollama("bld grp", "blood group", OLLAMA_URL, MODEL)
        # Should strip the "Note:" line and list markers
        assert "blood type" in result
        assert "blood group type" in result
        assert result[0] != "Note: Here are the alternatives."

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="This is a full sentence explaining the query which should be skipped because it is too long to be a retrieval term")
    def test_skips_sentence_like_lines(self, _mock):
        result = expand_with_ollama("test", "test", OLLAMA_URL, MODEL)
        # The single long line (8+ words) should be skipped
        assert len(result) == 0

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="blood type\nblood type\nblood group type")
    def test_deduplicates_expansions(self, _mock):
        result = expand_with_ollama("bld grp", "blood group", OLLAMA_URL, MODEL)
        assert result.count("blood type") == 1
        assert "blood group type" in result

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="blood type\nblood type\nblood group type\nmail address\n")
    def test_caps_at_three_variants(self, _mock):
        result = expand_with_ollama("bld grp", "blood group", OLLAMA_URL, MODEL)
        assert len(result) <= 3

    def test_no_ollama_url_returns_empty(self):
        """Without an ollama_url, expansion is skipped entirely."""
        result = expand_with_ollama("bld grp", "blood group", ollama_url=None, model=MODEL)
        assert result == []


# ── 5. _parse_expansion edge cases ───────────────────────────────────────────

class TestParseExpansion:
    def test_basic_parsing(self):
        response = "term one\nterm two\nterm three"
        assert _parse_expansion(response) == ["term one", "term two", "term three"]

    def test_strips_list_markers(self):
        response = "- bullet one\n* bullet two\n1. numbered one"
        result = _parse_expansion(response)
        assert result == ["bullet one", "bullet two", "numbered one"]

    def test_strips_bullet_and_number_variants(self):
        response = "• alpha\n1) beta\n2) gamma"
        result = _parse_expansion(response)
        assert result == ["alpha", "beta", "gamma"]

    def test_skips_meta_lines(self):
        response = "Note: this is a comment\nthe answer is here\nanswer: foo\nI would suggest bar\nreal term"
        result = _parse_expansion(response)
        assert "real term" in result
        for line in result:
            assert not line.lower().startswith(("note:", "the ", "answer:", "i would"))

    def test_truncates_at_sentence_end(self):
        response = "simple term. this should be cut off"
        result = _parse_expansion(response)
        assert result == ["simple term"]

    def test_empty_string(self):
        assert _parse_expansion("") == []

    def test_only_dots(self):
        assert _parse_expansion("...") == []

    def test_whitespace_only_lines(self):
        response = "  \n\n  \nreal term"
        result = _parse_expansion(response)
        assert result == ["real term"]

    def test_takes_first_phrase(self):
        """Each line is treated as a separate variant; the first phrase
        (up to any sentence-ending punctuation) is kept."""
        response = "first phrase\nsecond phrase\nthird phrase"
        result = _parse_expansion(response)
        assert result == ["first phrase", "second phrase", "third phrase"]

    def test_truncates_at_sentence_end_within_line(self):
        """A single line with an embedded period is truncated at the period."""
        response = "simple term. this should be cut off"
        result = _parse_expansion(response)
        assert result == ["simple term"]


# ── 6. generate_variants full pipeline ───────────────────────────────────────

class TestGenerateVariants:
    def test_always_returns_at_least_original(self):
        result = generate_variants("anything", OLLAMA_URL, MODEL)
        assert result[0] == "anything"
        assert len(result) >= 1

    @patch("services.retrieval.query_expander._ollama_generate", return_value=None)
    def test_without_ollama_adds_normalized_variant(self, _mock):
        """Abbreviation queries always get at least a normalized variant."""
        result = generate_variants("bld grp", OLLAMA_URL, MODEL)
        assert result[0] == "bld grp"
        assert "blood group" in result  # normalized form

    @patch("services.retrieval.query_expander._ollama_generate", return_value=None)
    def test_no_change_query_no_normalized_variant(self, _mock):
        """If normalize() produces the same result (lowercased), no extra variant added."""
        result = generate_variants("blood group", OLLAMA_URL, MODEL)
        assert result[0] == "blood group"
        # normalized is "blood group" == lowercased original → no normalized variant
        assert len(result) == 1

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="blood type\nmedical blood type")
    def test_full_pipeline_with_mocked_ollama(self, _mock):
        """bld grp: variant list = [original, normalized, ollama alternatives]."""
        result = generate_variants("bld grp", OLLAMA_URL, MODEL)
        assert result[0] == "bld grp"
        assert result[1] == "blood group"
        assert "blood type" in result
        assert "medical blood type" in result
        assert len(result) == 4

    @patch("services.retrieval.query_expander._ollama_generate", return_value=None)
    def test_rich_query_does_not_expand(self, _mock):
        """Rich queries (>=5 meaningful terms) skip Ollama entirely."""
        rich_query = ("detailed analysis of machine learning algorithms "
                       "and their applications in modern software engineering")
        result = generate_variants(rich_query, OLLAMA_URL, MODEL)
        assert result[0] == rich_query
        # Only the original + normalized (same lowercased) → no expansion
        normalized = normalize(rich_query)
        if normalized != rich_query.lower().strip():
            assert len(result) >= 2
        else:
            assert len(result) == 1
        _mock.assert_not_called()

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="email address\ncontact email")
    def test_email_query_variants(self, _mock):
        result = generate_variants("email", OLLAMA_URL, MODEL)
        assert "email" in result
        assert "email address" in result
        assert "contact email" in result

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="mobile phone\ncontact number")
    def test_phone_query_variants(self, _mock):
        result = generate_variants("phone", OLLAMA_URL, MODEL)
        assert "phone" in result
        assert "mobile phone" in result
        assert "contact number" in result

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="GPA\ncumulative grade point average")
    def test_cgpa_query_variants(self, _mock):
        result = generate_variants("CGPA", OLLAMA_URL, MODEL)
        assert "CGPA" in result  # original is case-preserved
        assert "GPA" in result
        assert "cumulative grade point average" in result

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="work projects\nprofessional experience")
    def test_projects_query_variants(self, _mock):
        result = generate_variants("projects", OLLAMA_URL, MODEL)
        assert "projects" in result
        assert "work projects" in result
        assert "professional experience" in result

    @patch("services.retrieval.query_expander._ollama_generate", return_value=None)
    def test_ollama_failure_still_returns_base_variants(self, _mock):
        """Ollama failure is soft — base variants are still returned."""
        result = generate_variants("bld grp", OLLAMA_URL, MODEL)
        assert result[0] == "bld grp"
        assert "blood group" in result
        # No Ollama alternatives, but we still have the original + normalized
        assert len(result) == 2

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="blood type\nbld grp\nblood group")
    @patch("services.retrieval.query_expander.get_settings")
    def test_deduplicates_against_existing_variants(self, _mock_settings, _mock_gen):
        """Ollama alternatives that duplicate existing variants are dropped."""
        from core.config import Settings
        _mock_settings.return_value = Settings()

        result = generate_variants("bld grp", OLLAMA_URL, MODEL)
        # "bld grp", "blood group", "blood type" — but "bld grp" and "blood group"
        # are already present so they're deduplicated from the Ollama output
        occurrences_bld_grp = sum(1 for v in result if v.lower().strip() == "bld grp")
        occurrences_blood_group = sum(1 for v in result if v.lower().strip() == "blood group")
        assert occurrences_bld_grp == 1
        assert occurrences_blood_group == 1
        assert "blood type" in result


# ── 7. Spec: query-variation coverage ────────────────────────────────────────

class TestSpecQueryVariations:
    """Verify that abbreviation-based phrasing collapses to the same search
    space so evidence chunks are retrievable regardless of formulation.

    blood group  /  bld grp  /  blood type
    email        /  mail
    phone        /  mobile   /  contact number
    CGPA         /  GPA
    projects     /  work done
    """

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="blood type\nblood group type\npatient blood")
    def test_blood_group_variations_collapse(self, _mock):
        """'bld grp' normalization + Ollama alt should cover 'blood type'."""
        result = generate_variants("bld grp", OLLAMA_URL, MODEL)
        # Original: bld grp → Normalized: blood group → Ollama: blood type, blood group type, patient blood
        assert "bld grp" in result
        assert "blood group" in result
        assert "blood type" in result
        assert "blood group type" in result

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="blood group type\nblood group\nred blood cells")
    def test_blood_type_variations(self, _mock):
        """'blood type' should also expand to 'blood group' to find the same docs."""
        result = generate_variants("blood type", OLLAMA_URL, MODEL)
        assert "blood type" in result
        assert "blood group" in result
        assert "blood group type" in result

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="postal address\ncontact email\nmail")
    def test_email_and_mail_coverage(self, _mock):
        """'email' Ollama expansion should yield 'mail' as a variant."""
        result = generate_variants("email", OLLAMA_URL, MODEL)
        assert "email" in result
        assert "mail" in result

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="email address\nelectronic mail\nemail")
    def test_mail_to_email_coverage(self, _mock):
        """'mail' should expand to find 'email' documents."""
        result = generate_variants("mail", OLLAMA_URL, MODEL)
        assert "mail" in result
        assert "email" in result
        assert "email address" in result

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="mobile phone\ncontact number\ntelephone")
    def test_phone_to_mobile_to_contact(self, _mock):
        """'phone' variants should cover 'mobile' and 'contact number'."""
        result = generate_variants("phone", OLLAMA_URL, MODEL)
        assert "phone" in result
        assert "mobile phone" in result
        assert "contact number" in result

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="phone number\nmobile\nSMS")
    def test_mobile_to_phone_coverage(self, _mock):
        result = generate_variants("mobile", OLLAMA_URL, MODEL)
        assert "mobile" in result
        assert "phone number" in result

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="phone\nmobile number\ntelephone")
    def test_contact_number_coverage(self, _mock):
        result = generate_variants("contact number", OLLAMA_URL, MODEL)
        assert "contact number" in result
        assert "phone" in result
        assert "mobile number" in result

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="GPA\ncumulative GPA\ngrade point average")
    def test_cgpa_to_gpa_coverage(self, _mock):
        result = generate_variants("CGPA", OLLAMA_URL, MODEL)
        assert "CGPA" in result
        assert "GPA" in result

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="CGPA\ncumulative grade\nscore")
    def test_gpa_to_cgpa_coverage(self, _mock):
        result = generate_variants("GPA", OLLAMA_URL, MODEL)
        assert "GPA" in result
        assert "CGPA" in result

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="work experience\nprofessional projects\nportfolio")
    def test_projects_to_work_done_coverage(self, _mock):
        result = generate_variants("projects", OLLAMA_URL, MODEL)
        assert "projects" in result
        assert "work experience" in result
        assert "professional projects" in result

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="projects\nassignments done\nwork portfolio")
    def test_work_done_to_projects_coverage(self, _mock):
        result = generate_variants("work done", OLLAMA_URL, MODEL)
        assert "work done" in result
        assert "projects" in result


# ── 8. Integration-style: variant coverage across phrasings ─────────────────

class TestCrossPhraseCoverage:
    """Confirm that semantically equivalent phrasing produces overlapping
    variant sets so that RRF fusion retrieves the same chunks."""

    @patch("services.retrieval.query_expander._ollama_generate",
           return_value="blood type\nblood group type\npatient blood")
    def test_abbreviation_and_canonical_overlap(self, _mock):
        """'bld grp' (normalized → 'blood group') and 'blood group' should
        produce overlapping variant sets."""
        abbr_result = generate_variants("bld grp", OLLAMA_URL, MODEL)
        canonical_result = generate_variants("blood group", OLLAMA_URL, MODEL)

        # Both should contain 'blood group' (canonical form)
        assert "blood group" in abbr_result
        abbr_normalized = normalize("bld grp")
        assert abbr_normalized == "blood group"

        # abbr_result has extra variants from Ollama expansion
        assert len(abbr_result) > len(canonical_result) or len(canonical_result) == 1

    @patch("services.retrieval.query_expander._ollama_generate", return_value=None)
    def test_abbreviation_normalization_no_ollama(self, _mock):
        """Without Ollama, only normalization bridges the gap."""
        result = generate_variants("bld grp", OLLAMA_URL, MODEL)
        assert "bld grp" in result
        assert "blood group" in result
        # bld → blood, grp → group
        normalized = normalize("bld grp")
        assert "blood" in normalized
        assert "group" in normalized


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

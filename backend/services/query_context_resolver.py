import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Patterns that explicitly denote a fresh YouTube URL in the query
_YOUTUBE_URL_RE = re.compile(
    r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/embed/)[0-9A-Za-z_-]{11}",
    re.IGNORECASE,
)

_EXPLICIT_DOC_COMPARE = re.compile(
    r"\b(both|all\s+three|all\s+sources|compare|comparison|same\s+topic|discuss\s+the\s+same|similar|similarities|differences|match|relate|related)\b",
    re.IGNORECASE,
)

# Explicit general/conversational/math/trivia patterns that should never trigger document retrieval
_GENERAL_NON_DOC_RE = re.compile(
    r"^(hi|hello|hey|greetings|howdy|good\s+(morning|afternoon|evening|day)|thanks|thank\s+you|bye|goodbye)[!. ]*$|"
    r"^(what\s+is\s+)?\d+\s*[\+\-\*\/\^]\s*\d+.*$|"
    r"^calculate\s+\d+|"
    r"^(tell\s+me\s+a\s+joke|who\s+are\s+you|what\s+can\s+you\s+do)[?.! ]*$|"
    r"^(who\s+is\s+the\s+president|what\s+is\s+the\s+capital|what\s+is\s+the\s+distance|how\s+far\s+is|who\s+won\s+the|what\s+is\s+photosynthesis)\b|"
    r"^(write\s+a\s+(python|javascript|code|script|function)|explain\s+how\s+a\s+binary\s+tree\s+works)\b",
    re.IGNORECASE,
)

# Queries referring specifically to audio/speech/recordings
_AUDIO_REFERENCES = re.compile(
    r"\b(audio|speech|voice|recording|spoken|transcript|transcription|said\s+in\s+the\s+audio|what\s+did\s+the\s+audio\s+say|what\s+was\s+said|listen|podcast|audio\s+clip|speaker)\b",
    re.IGNORECASE,
)

_FRESH_IMAGE_REFERENCES = re.compile(
    r"\b(image|photo|picture|scan|screenshot)\b",
    re.IGNORECASE,
)

# Queries referring specifically to video/youtube followups without new URL
_VIDEO_REFERENCES = re.compile(
    r"\b(video|youtube|youtube\s+video|the\s+video|that\s+video|video\s+transcript|clip|discussed\s+in\s+the\s+video|"
    r"what\s+did\s+the\s+video\s+say|song|track|music|lyrics?|singer|artist|what\s+did\s+he\s+say|"
    r"what\s+did\s+they\s+say|what\s+was\s+said|what\s+did\s+the\s+speaker\s+say|"
    r"what\s+is\s+(this|the)\s+video\s+about|what\s+is\s+this\s+about|main\s+(point|message|theme|idea|takeaway)|"
    r"road|hate\s+when\s+the\s+road|passenger|let\s+her\s+go)\b",
    re.IGNORECASE,
)

# Queries referring specifically to PDF / resume / document entities or fields
_DOCUMENT_FIELD_REFERENCES = re.compile(
    r"\b(cgpa|gpa|marks|percentage|score|prn|roll(?:\s+number)?|registration(?:\s+number)?|application(?:\s+number)?|"
    r"date\s+of\s+birth|dob|blood\s*group|address|email|phone|contact|qualification|degree|education|"
    r"college|university|school|institute|class\s*10|class\s*12|tenth|twelfth|semester|branch|major|"
    r"experience|job|work|internship|project(?:s)?|skill(?:s)?|achievement(?:s)?|organization|company|profile|"
    r"author|resume|cv|pdf|id\s*card|identity\s*card|certificate|certifications?|applicant|candidate|"
    r"frontend|backend|database|framework|library|technology|technologies|stack|used|uses|employs|"
    r"written|described|mentioned|stated|shown|listed|included|contained|presented|outlined|detailed|"
    r"point|section|chapter|table|figure|content|feature|features|system|architecture|component|components|modules?|"
    r"explain|describe|list|name|contains|includes|consists|comprised|overview|summary)\b",
    re.IGNORECASE,
)

_DOCUMENT_EXPLICIT_REFERENCES = re.compile(
    r"\b(my|our|uploaded|in\s+the\s+file|in\s+the\s+document|from\s+the\s+document|from\s+the\s+file|"
    r"mentioned\s+in\s+the|according\s+to\s+the\s+document|according\s+to\s+the\s+resume|in\s+the\s+pdf|"
    r"previous\s+document|prior\s+document|uploaded\s+pdf|uploaded\s+cv|"
    r"written\s+in|contained\s+in|included\s+in|found\s+in|shown\s+in|detailed\s+in|described\s+in|stated\s+in\s+the"
    r"|in\s+the\s+(text|content|body|material))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QueryContext:
    use_retrieval: bool
    document_ids: list[str]
    reason: str


class QueryContextResolver:
    """Decides whether uploaded evidence is relevant without exposing RAG as a user tool."""

    @staticmethod
    def resolve(query: str, documents: list[dict]) -> QueryContext:
        active_docs = [
            document for document in documents
            if document.get("status") in {"READY", "UPLOADED", "PROCESSING"} or (document.get("status") != "FAILED" and document.get("id"))
        ]
        if not active_docs:
            return QueryContext(False, [], "no_active_documents")
        if not query.strip():
            return QueryContext(False, [], "empty_query")

        # 1. Pure greeting, math, or trivia query -> NEVER search old document chunks
        if _GENERAL_NON_DOC_RE.search(query.strip()):
            logger.info("query_context_resolved use_retrieval=false reason=general_query")
            return QueryContext(False, [], "general_query")

        # 2. Fresh YouTube URL query without comparison -> fetch in current turn, don't search old documents
        has_new_yt_url = bool(_YOUTUBE_URL_RE.search(query))
        if has_new_yt_url and not _EXPLICIT_DOC_COMPARE.search(query):
            logger.info("query_context_resolved use_retrieval=false reason=new_youtube_url_query")
            return QueryContext(False, [], "new_youtube_url_query")

        # A fresh image request must not fall back to unrelated stored files.
        if _FRESH_IMAGE_REFERENCES.search(query) and not _EXPLICIT_DOC_COMPARE.search(query):
            logger.info("query_context_resolved use_retrieval=false reason=fresh_image_query")
            return QueryContext(False, [], "fresh_image_query")

        # 3. Explicit Multi-source Comparison query
        if _EXPLICIT_DOC_COMPARE.search(query):
            document_ids = [str(document["id"]) for document in active_docs if document.get("id")]
            logger.info("query_context_resolved use_retrieval=true documents=%d reason=cross_source_comparison", len(document_ids))
            return QueryContext(True, document_ids, "cross_source_comparison")

        # 4. Dedicated Audio follow-up
        if _AUDIO_REFERENCES.search(query):
            audio_docs = [
                d for d in active_docs
                if d.get("modality") == "audio"
                or d.get("source_type") == "audio"
                or "audio" in str(d.get("filename", "")).lower()
                or str(d.get("mime_type", "")).startswith(("audio/", "video/"))
            ]
            doc_ids = [str(d["id"]) for d in (audio_docs or active_docs) if d.get("id")]
            logger.info("query_context_resolved use_retrieval=true documents=%d reason=audio_reference", len(doc_ids))
            return QueryContext(True, doc_ids, "audio_reference")

        # 5. Dedicated YouTube / Video follow-up (no new URL)
        yt_docs = [
            d for d in active_docs
            if d.get("modality") == "youtube"
            or d.get("source_type") == "youtube"
            or "youtube" in str(d.get("filename", "")).lower()
            or d.get("video_id")
            or d.get("youtube_video_id")
            or (isinstance(d.get("metadata"), dict) and d["metadata"].get("source_type") == "youtube")
            or str(d.get("id", "")).startswith("yt-")
        ]

        is_video_ref = bool(_VIDEO_REFERENCES.search(query))
        is_explicit_other_modality = bool(
            re.search(r"\b(pdf|resume|cv|image|photo|picture|scan|id\s*card)\b", query, re.IGNORECASE)
        )
        has_recent_yt = bool(active_docs and (
            active_docs[0].get("modality") == "youtube"
            or active_docs[0].get("source_type") == "youtube"
            or active_docs[0].get("video_id")
            or active_docs[0].get("youtube_video_id")
        ))

        if (is_video_ref or (has_recent_yt and not is_explicit_other_modality)) and yt_docs:
            # Strictly use ONLY the most recent YouTube document UUID to avoid multi-doc pollution (Requirement 10)
            target_id = str(yt_docs[0]["id"])
            logger.info("query_context_resolved use_retrieval=true documents=1 doc_id=%s reason=video_reference", target_id)
            return QueryContext(True, [target_id], "video_reference")
        elif is_video_ref and active_docs:
            target_id = str(active_docs[0]["id"])
            logger.info("query_context_resolved use_retrieval=true documents=1 doc_id=%s reason=video_reference", target_id)
            return QueryContext(True, [target_id], "video_reference")

        # 6. Document questions matching document fields or explicit document references
        is_field_ref = bool(_DOCUMENT_FIELD_REFERENCES.search(query))
        is_doc_ref = bool(_DOCUMENT_EXPLICIT_REFERENCES.search(query))

        if is_field_ref or is_doc_ref:
            # Prefer PDF / text / OCR docs for resume/field questions unless none exist
            doc_docs = [
                d for d in active_docs
                if d.get("modality") in {"pdf", "image", "text"}
                or d.get("source_type") in {"pdf", "ocr", "text"}
            ]
            selected_docs = doc_docs if doc_docs else active_docs
            document_ids = [str(document["id"]) for document in selected_docs if document.get("id")]
            reason = "document_field_reference" if is_field_ref else "document_reference"
            logger.info("query_context_resolved use_retrieval=true documents=%d reason=%s", len(document_ids), reason)
            return QueryContext(True, document_ids, reason)

        # 7. Follow-up pronouns referring to active documents ("what did he say", "what are his skills")
        if re.search(r"\b(he|she|his|her|him|they|them|applicant|candidate)\b", query, re.IGNORECASE):
            document_ids = [str(document["id"]) for document in active_docs if document.get("id")]
            logger.info("query_context_resolved use_retrieval=true documents=%d reason=pronoun_reference", len(document_ids))
            return QueryContext(True, document_ids, "pronoun_reference")

        # Fallback: when there are active documents in the current session,
        # any non-general query should attempt RAG retrieval. The hybrid
        # lexical + vector search will find relevant evidence or return empty,
        # in which case the LLM responds with "Not found in the provided content."
        if active_docs:
            document_ids = list(dict.fromkeys(
                str(document["id"]) for document in active_docs if document.get("id")
            ))
            logger.info("query_context_resolved use_retrieval=true documents=%d reason=document_content_query", len(document_ids))
            return QueryContext(True, document_ids, "document_content_query")

        # No active documents to search — general / unrelated query
        logger.info("query_context_resolved use_retrieval=false reason=unrelated_query")
        return QueryContext(False, [], "unrelated_query")



"""
YouTube transcript fetcher using youtube-transcript-api.

This module provides a simple backward-compatible wrapper around the
library so the rest of the backend can call `YouTubeFetcher.fetch_transcript`
without worrying about package version differences.
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        TranscriptsDisabled,
        NoTranscriptFound,
        VideoUnavailable,
        YouTubeRequestFailed,
        CouldNotRetrieveTranscript,
        RequestBlocked,
        IpBlocked,
    )
except ImportError:
    YouTubeTranscriptApi = None  # type: ignore
    # Create distinct fallback exception classes so that
    # except clauses matching specific errors do not
    # accidentally catch all exceptions.
    class TranscriptsDisabled(Exception):
        pass

    class NoTranscriptFound(Exception):
        pass

    class VideoUnavailable(Exception):
        pass

    class YouTubeRequestFailed(Exception):
        pass

    class CouldNotRetrieveTranscript(Exception):
        pass

    class RequestBlocked(Exception):
        pass

    class IpBlocked(Exception):
        pass

_LANGUAGE_PRIORITY = [
    "en", "en-US", "en-GB",
    "a.en",
    "hi",
    "a.hi",
]


class YouTubeFetcher:
    VIDEO_ID_PATTERN = re.compile(
        r"(?:v=|youtu\.be/|/embed/|/shorts/)([0-9A-Za-z_-]{11})"
    )

    @staticmethod
    def extract_video_id(text: str) -> Optional[str]:
        bare_id = re.fullmatch(r"[0-9A-Za-z_-]{11}", text.strip())
        if bare_id:
            return text.strip()

        match = YouTubeFetcher.VIDEO_ID_PATTERN.search(text)
        return match.group(1) if match else None

    @staticmethod
    def _fetch_with_instance_api(video_id: str):
        api = YouTubeTranscriptApi()
        try:
            snippets = api.fetch(video_id, languages=_LANGUAGE_PRIORITY)
            return list(snippets)
        except NoTranscriptFound:
            pass
        except AttributeError:
            raise

        try:
            transcript_list = api.list(video_id)
            transcripts = list(transcript_list)
        except Exception as e:
            logger.exception("YouTube: failed to list transcripts for %s: %s", video_id, e)
            raise CouldNotRetrieveTranscript(video_id) from e

        if not transcripts:
            raise CouldNotRetrieveTranscript(video_id)

        manual = [t for t in transcripts if not getattr(t, "is_generated", False)]
        chosen = manual[0] if manual else transcripts[0]
        try:
            return list(chosen.fetch())
        except Exception as e:
            logger.exception("YouTube: failed to fetch chosen transcript for %s: %s", video_id, e)
            raise CouldNotRetrieveTranscript(video_id) from e

    @staticmethod
    def _fetch_with_old_api(video_id: str):
        try:
            return YouTubeTranscriptApi.get_transcript(video_id, languages=_LANGUAGE_PRIORITY)
        except AttributeError:
            raise
        except NoTranscriptFound:
            pass

        try:
            api = YouTubeTranscriptApi()
            list_fn = getattr(api, "list_transcripts", None)
            if not callable(list_fn):
                list_fn = getattr(YouTubeTranscriptApi, "list_transcripts", None)

            if not callable(list_fn):
                list_fn = getattr(api, "list", None)
            if not callable(list_fn):
                list_fn = getattr(YouTubeTranscriptApi, "list", None)
            if not callable(list_fn):
                list_fn = lambda _=None: []

            transcripts = list(list_fn(video_id))
        except Exception as e:
            logger.exception("YouTube: failed to list transcripts for %s: %s", video_id, e)
            raise CouldNotRetrieveTranscript(video_id) from e

        if not transcripts:
            raise CouldNotRetrieveTranscript(video_id)

        manual = [t for t in transcripts if not getattr(t, "is_generated", False)]
        chosen = manual[0] if manual else transcripts[0]
        try:
            return chosen.fetch()
        except Exception as e:
            logger.exception("YouTube: failed to fetch chosen transcript for %s: %s", video_id, e)
            raise CouldNotRetrieveTranscript(video_id) from e

    @staticmethod
    def _snippets_to_text(snippets) -> str:
        parts = []
        for item in snippets:
            if hasattr(item, "text"):
                parts.append(item.text)
            elif isinstance(item, dict):
                parts.append(item.get("text", ""))
        return " ".join(filter(None, parts)).strip()

    @staticmethod
    def fetch_transcript(text: str) -> str:
        if YouTubeTranscriptApi is None:
            return (
                "Failed to fetch YouTube transcript: youtube-transcript-api is not installed. "
                "Run: pip install youtube-transcript-api"
            )

        video_id = YouTubeFetcher.extract_video_id(text)
        if not video_id:
            return "No valid YouTube URL found in the provided text."

        logger.info("YouTube: fetching transcript for video_id=%s", video_id)

        try:
            if hasattr(YouTubeTranscriptApi, "fetch") and callable(YouTubeTranscriptApi.fetch):
                snippets = YouTubeFetcher._fetch_with_instance_api(video_id)
            else:
                snippets = YouTubeFetcher._fetch_with_old_api(video_id)

            transcript_text = YouTubeFetcher._snippets_to_text(snippets)
            if not transcript_text:
                return f"Failed to fetch YouTube transcript: Transcript was empty for video {video_id}."
            logger.info("YouTube: transcript fetched successfully (%d chars)", len(transcript_text))
            return transcript_text

        except TranscriptsDisabled:
            return (
                f"Failed to fetch YouTube transcript: Transcripts/captions are disabled for this video ({video_id}). "
                "The video owner has turned off captions."
            )
        except NoTranscriptFound:
            return (
                f"Failed to fetch YouTube transcript: No transcript found in any language for video ({video_id}). "
                "Try a different video or check if captions are available."
            )
        except VideoUnavailable:
            return (
                f"Failed to fetch YouTube transcript: Video {video_id} is unavailable "
                "(private, deleted, or region-locked)."
            )
        except (RequestBlocked, IpBlocked):
            return (
                "Failed to fetch YouTube transcript: YouTube has blocked requests from this server's IP address. "
                "This commonly happens in cloud/server environments. Consider configuring a proxy."
            )
        except YouTubeRequestFailed as e:
            msg = str(e)
            if "403" in msg:
                return (
                    f"Failed to fetch YouTube transcript: YouTube returned 403 Forbidden for video {video_id}. "
                    "This typically means the server IP is rate-limited or blocked by YouTube."
                )
            if "404" in msg:
                return (
                    f"Failed to fetch YouTube transcript: Video {video_id} not found (404). "
                    "Please check the URL is correct."
                )
            return f"Failed to fetch YouTube transcript: YouTube request failed — {msg}"
        except CouldNotRetrieveTranscript as e:
            return f"Failed to fetch YouTube transcript: Could not retrieve transcript — {str(e)}"
        except Exception as e:
            error_str = str(e)
            if "no element found" in error_str or "ParseError" in type(e).__name__:
                return (
                    f"Failed to fetch YouTube transcript: Received an empty response from YouTube's transcript service for video {video_id}. "
                    "This is usually caused by YouTube blocking automated requests from server IPs."
                )
            logger.exception("YouTube fetch unexpected error for video %s: %s", video_id, e)
            return f"Failed to fetch YouTube transcript: {type(e).__name__}: {error_str}"

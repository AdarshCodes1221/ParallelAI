import logging
import os

logger = logging.getLogger(__name__)


class TTSService:
    """
    Text-to-Speech service using gTTS.
    Converts a text string to an MP3 file and returns the file path.
    """

    @staticmethod
    def generate(text: str, output_path: str = "temp_uploads/tts_output.mp3") -> str | None:
        """
        Converts text to speech and saves as MP3.
        Returns the file path on success, None on failure.
        """
        try:
            from gtts import gTTS

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            tts = gTTS(text=text, lang="en", slow=False)
            tts.save(output_path)
            logger.info(f"[TTS] Audio saved to {output_path}")
            return output_path

        except ImportError:
            logger.warning("[TTS] gTTS not installed. Run: pip install gTTS")
            return None
        except Exception as e:
            logger.error(f"[TTS] Failed to generate audio: {e}")
            return None
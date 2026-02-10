import logging
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

# Global variable to hold the model in memory
_model = None

def load_model():
    """
    Loads the model into memory only when needed (Lazy Loading).
    Using 'base' model with int8 quantization for speed on laptop/CPU.
    """
    global _model
    if _model is None:
        logger.info("⏳ Loading Whisper Model (this happens once)...")
        # device="cpu" is safest for laptops.
        _model = WhisperModel("base", device="cpu", compute_type="int8")
        logger.info("✅ Whisper Model Loaded.")
    return _model

def transcribe_audio(file_path):
    """
    Takes an .ogg/.mp3 file path, returns the transcribed text string.
    """
    if not file_path:
        logger.error("No file path provided for transcription.")
        return ""
        
    try:
        model = load_model()
        segments, info = model.transcribe(file_path, beam_size=5)
        
        # Combine all segments into one string
        text = " ".join([segment.text for segment in segments]).strip()
        return text
    except Exception as e:
        logger.error(f"Transcription Failed: {e}")
        return "[Error extracting text]"

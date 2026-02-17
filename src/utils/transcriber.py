import os
import logging
import asyncio
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
MODEL_SIZE = "tiny" # or "base" for better accuracy if CPU allows
CPU_THREADS = 4     # Limit threads per job

# --- GLOBAL STATE ---
# We load the model ONCE globally, not every time a function runs.
_model_instance = None 

# AWS GUARD: Only allow 1 transcription job at a time
_transcription_lock = asyncio.Semaphore(1)

def get_model():
    """Lazy-loads the model only when first needed."""
    global _model_instance
    if _model_instance is None:
        logger.info(f"⬇️ Loading Whisper Model ({MODEL_SIZE})...")
        _model_instance = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8", cpu_threads=CPU_THREADS)
    return _model_instance

def _run_sync_transcribe(file_path):
    """The blocking CPU-heavy function."""
    try:
        model = get_model()
        segments, _ = model.transcribe(file_path, beam_size=1)
        text = " ".join([segment.text for segment in segments]).strip()
        return text
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return ""

async def transcribe_audio(file_path: str) -> str:
    """
    Async wrapper that waits for the Semaphore lock before processing.
    This prevents the AWS server from crashing under load.
    """
    if not os.path.exists(file_path):
        return ""

    # Wait for the lock (Queue system)
    async with _transcription_lock:
        logger.info(f"🎙️ Starting transcription for {os.path.basename(file_path)}")
        
        # Run the heavy blocking code in a separate thread, managed by asyncio
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, _run_sync_transcribe, file_path)
        
        logger.info(f"✅ Transcription done: {text[:30]}...")
        return text
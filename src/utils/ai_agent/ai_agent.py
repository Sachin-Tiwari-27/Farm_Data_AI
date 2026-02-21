import os
import logging
import asyncio
from typing import List, Optional
from google import genai
from google.genai import types
from PIL import Image
from utils.ai_agent.ai_prompts import build_agronomist_prompt

logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Limit to 3 concurrent AI calls to protect CPU and API rate limits
ai_semaphore = asyncio.Semaphore(3)

# Models to try in order
MODELS = ["gemini-2.5-flash"]

async def ask_ai(user_query: str, image_paths: Optional[List[str]] = None, 
                 weather: dict = None, location: dict = None) -> dict:
    """
    2026-ready AI Agent using google-genai SDK.
    """
    
    async with ai_semaphore:
    
        # 1. Build the Engineered Prompt
        full_prompt = build_agronomist_prompt(user_query, weather, location)
    
        # 2. Prepare Content
        content_parts = [full_prompt]
        if image_paths:
            for path in image_paths:
                if os.path.exists(path):
                    try:
                        content_parts.append(Image.open(path))
                    except Exception as e:
                        logger.error(f"Img load error: {e}")

        # 3. Execution Loop
        model_id = MODELS[0]
    
        for attempt in range(2): # Try twice
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model_id,
                    contents=content_parts
                )
            
                # Check if text exists (Safety filters can return 200 OK but empty text)
                if response.text:
                    # Clean markdown escaping which breaks Telegram
                    clean_text = response.text.replace("\\", "").replace("`", "'")
                    return {"text": clean_text, "model_used": model_id}
                else:
                    logger.warning(f"⚠️ API returned 200 OK but empty text (Safety Block? Attempt {attempt+1})")
        
            except Exception as e:
                if "429" in str(e): # Rate limit
                    logger.warning(f"Quota hit on {model_id}. Retrying...")
                    await asyncio.sleep(2)
                    continue
                else:
                    logger.error(f"Error on {model_id}: {e}")
                    break

        # 4. FALLBACK (CRITICAL FIX: Must include 'model_used')
        return {
            "text": "⚠️ I couldn't generate a response. The image might have triggered safety filters or the system is busy.", 
            "model_used": "System_Fallback"
        }
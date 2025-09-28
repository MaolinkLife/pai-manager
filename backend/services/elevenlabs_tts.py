import requests


async def generate_elevenlabs_tts(text: str, filename: str, config: dict) -> None:
    api_key = config.get("api_key")
    voice_id = config.get("voice_id")
    model_id = config.get("model_id", "eleven_multilingual_v2")
    stability = config.get("stability", 0.5)
    similarity = config.get("similarity", 0.75)

    if not api_key or not voice_id:
        raise RuntimeError("Missing ElevenLabs API Key or Voice ID.")

    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}

    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {"stability": stability, "similarity_boost": similarity},
    }

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

    try:
        response = requests.post(url, headers=headers, json=payload, stream=True)
        if response.status_code == 200:
            with open(filename, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
        else:
            raise RuntimeError(
                f"[ElevenLabs] API error {response.status_code}: {response.text}"
            )
    except Exception as e:
        raise RuntimeError(f"[ElevenLabs] TTS generation failed: {str(e)}")

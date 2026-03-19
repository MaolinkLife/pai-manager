import numpy as np
import re
import unicodedata

# Next 2 lines are a fix for fairseq to be compatible with pytorch > 2.6
import sys
sys.path = [str(p) for p in sys.path]

from fairseq import checkpoint_utils
import torch
import logging

logging.getLogger("fairseq").setLevel(logging.WARNING)
import sys
import numpy as np
import ffmpeg
from pathlib import Path
from constants.paths import RVC_MODELS_DIR

RVC_ROOT = Path(RVC_MODELS_DIR)

def load_audio(file, sampling_rate):
    try:
        file = str(file).strip(" ").strip('"').strip("\n").strip('"').strip(" ")

        try:
            # Use ffmpeg-python
            stream = (
                ffmpeg
                .input(file)
                .output('pipe:', format='f32le', acodec='pcm_f32le', ac=1, ar=str(sampling_rate))
                .run(capture_stdout=True, capture_stderr=True)
            )
            out = stream[0]  # Get stdout data
            
        except ffmpeg.Error as e:
            print(f"FFmpeg error: {e.stderr.decode('utf-8')}")
            raise RuntimeError(f"FFmpeg error: {e.stderr.decode('utf-8')}") from e

        return np.frombuffer(out, np.float32).flatten()

    except Exception as error:
        print(f"Error loading audio: {error}")
        raise RuntimeError(f"Failed to load audio: {error}") from error



def format_title(title):
    formatted_title = (
        unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("utf-8")
    )
    formatted_title = re.sub(r"[\u2500-\u257F]+", "", formatted_title)
    formatted_title = re.sub(r"[^\w\s.-]", "", formatted_title)
    formatted_title = re.sub(r"\s+", "_", formatted_title)
    return formatted_title


def load_embedding(embedder_model):
    embedding_list = {
        "contentvec": "contentvec_base.pt",
        "hubert": "hubert_base.pt",
    }
    
    try:
        file_name = embedding_list[embedder_model]
        model_path = RVC_ROOT / "embedder" / file_name
        if not model_path.exists():
            legacy_path = RVC_ROOT / file_name
            if legacy_path.exists():
                logging.warning(
                    "Using legacy RVC embedder path for %s. Move it into storage/models/rvc/embedder.",
                    embedder_model,
                )
                model_path = legacy_path
        
        # Import Dictionary class from fairseq
        from fairseq.data.dictionary import Dictionary
        
        # For PyTorch 2.2+, try using add_safe_globals directly but with proper import 
        # of the Dictionary class from fairseq
        try:
            torch.serialization.add_safe_globals([Dictionary])
        except (AttributeError, ImportError) as e:
            # If add_safe_globals doesn't exist, we'll need to load with weights_only=False
            # But that's a security risk with untrusted models
            logging.warning("Could not use add_safe_globals, loading model with reduced security")
            pass
        
        # Load model
        models = checkpoint_utils.load_model_ensemble_and_task(
            [str(model_path)],
            suffix="",
        )
        
        return models
    except KeyError as e:
        logging.error(f"Invalid embedder model name: {embedder_model}")
        raise ValueError(f"Invalid embedder model name: {embedder_model}") from e
    except Exception as e:
        logging.error(f"Error loading embedding model: {e}")
        raise RuntimeError(f"Error loading embedding model: {e}") from e

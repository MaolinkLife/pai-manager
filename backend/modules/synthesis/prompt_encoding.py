"""Long and weighted prompts for CLIP-based checkpoints (SD 1.x, SDXL).

A CLIP text encoder sees 77 tokens at a time. A diffusers pipeline given a
prompt string cuts it there and reads "(worst quality:2)" as plain text.
ComfyUI instead encodes the prompt in 77-token chunks, joins them and applies
the weights. PAI generates without ComfyUI, so core does the same here and
hands the pipeline ready embeddings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Families whose pipelines encode prompts with CLIP text encoders.
CLIP_PROMPT_FAMILIES = frozenset(
    {"stable-diffusion-checkpoint", "sdxl-checkpoint", "stable-diffusion", "sdxl"}
)
# Content tokens per chunk: with the start and end tokens a chunk fills the
# 77-token CLIP window.
CHUNK_CONTENT_TOKENS = 75
EMPHASIS = 1.1

_ATTENTION_TOKEN = re.compile(
    r"\\\(|\\\)|\\\[|\\\]|\\\\|\\|\(|\[|:\s*([+-]?(?:\d+\.?\d*|\.\d+))\s*\)|\)|\]|[^\\()\[\]:]+|:"
)


def parse_weighted_prompt(text: Optional[str]) -> List[Tuple[str, float]]:
    """Split a prompt into (text, weight) segments.

    "(a:1.3)" sets a weight, "(a)" multiplies it by 1.1, "[a]" divides it by
    1.1, brackets nest, "\\(" is a literal bracket. A bracket left open still
    applies to the rest of the prompt.
    """
    segments: List[List[Any]] = []
    round_open: List[int] = []
    square_open: List[int] = []

    def scale_from(start: int, factor: float) -> None:
        for index in range(start, len(segments)):
            segments[index][1] *= factor

    for match in _ATTENTION_TOKEN.finditer(text or ""):
        token = match.group(0)
        explicit_weight = match.group(1)
        if token.startswith("\\") and len(token) == 2:
            segments.append([token[1], 1.0])
        elif token == "(":
            round_open.append(len(segments))
        elif token == "[":
            square_open.append(len(segments))
        elif explicit_weight is not None and round_open:
            scale_from(round_open.pop(), float(explicit_weight))
        elif token == ")" and round_open:
            scale_from(round_open.pop(), EMPHASIS)
        elif token == "]" and square_open:
            scale_from(square_open.pop(), 1 / EMPHASIS)
        else:
            segments.append([token, 1.0])

    for start in round_open:
        scale_from(start, EMPHASIS)
    for start in square_open:
        scale_from(start, 1 / EMPHASIS)

    merged: List[Tuple[str, float]] = []
    for part, weight in segments:
        if merged and abs(merged[-1][1] - weight) < 1e-9:
            merged[-1] = (merged[-1][0] + part, merged[-1][1])
        else:
            merged.append((part, weight))
    return merged or [("", 1.0)]


@dataclass
class TokenChunk:
    token_ids: List[int]
    weights: List[float]


def _chunk(tokenizer: Any, ids: Sequence[int], weights: Sequence[float]) -> TokenChunk:
    pad = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id
    token_ids = [tokenizer.bos_token_id, *ids, tokenizer.eos_token_id]
    chunk_weights = [1.0, *weights, 1.0]
    missing = CHUNK_CONTENT_TOKENS + 2 - len(token_ids)
    return TokenChunk(token_ids + [pad] * missing, chunk_weights + [1.0] * missing)


def tokenize_weighted(tokenizer: Any, segments: Sequence[Tuple[str, float]]) -> Tuple[List[TokenChunk], int]:
    """Tokens of all segments cut into 77-token chunks; returns the chunks and the token count."""
    ids: List[int] = []
    weights: List[float] = []
    for part, weight in segments:
        # tokenize + convert instead of calling the tokenizer: the length is
        # handled by chunking, so its "longer than 77 tokens" warning is noise.
        part_ids = list(tokenizer.convert_tokens_to_ids(tokenizer.tokenize(part)))
        ids.extend(part_ids)
        weights.extend([weight] * len(part_ids))
    chunks = [
        _chunk(tokenizer, ids[start:start + CHUNK_CONTENT_TOKENS], weights[start:start + CHUNK_CONTENT_TOKENS])
        for start in range(0, len(ids), CHUNK_CONTENT_TOKENS)
    ]
    return chunks or [_chunk(tokenizer, [], [])], len(ids)


@dataclass
class EncodedPrompt:
    prompt_embeds: Any
    negative_prompt_embeds: Any
    pooled_prompt_embeds: Any = None
    negative_pooled_prompt_embeds: Any = None
    prompt_tokens: int = 0
    negative_tokens: int = 0
    chunks: int = 0
    weighted_segments: int = 0

    def pipeline_kwargs(self) -> Dict[str, Any]:
        kwargs = {
            "prompt_embeds": self.prompt_embeds,
            "negative_prompt_embeds": self.negative_prompt_embeds,
        }
        if self.pooled_prompt_embeds is not None:
            kwargs["pooled_prompt_embeds"] = self.pooled_prompt_embeds
            kwargs["negative_pooled_prompt_embeds"] = self.negative_pooled_prompt_embeds
        return kwargs

    def audit_details(self) -> Dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "negative_tokens": self.negative_tokens,
            "chunks": self.chunks,
            "weighted_segments": self.weighted_segments,
        }


def _encode_chunk(encoder: Any, chunk: TokenChunk, device: Any, *, penultimate: bool) -> Tuple[Any, Any]:
    import torch

    input_ids = torch.tensor([chunk.token_ids], dtype=torch.long, device=device)
    output = encoder(input_ids, output_hidden_states=True)
    hidden = output.hidden_states[-2] if penultimate else output[0]
    return hidden, output[0]


def _apply_weights(hidden: Any, empty_hidden: Any, weights: Sequence[float]) -> Any:
    """ComfyUI's weighting: move each weighted token away from the empty prompt."""
    import torch

    if all(abs(weight - 1.0) < 1e-9 for weight in weights):
        return hidden
    factors = torch.tensor(list(weights), dtype=hidden.dtype, device=hidden.device).view(1, -1, 1)
    weighted = empty_hidden + (hidden - empty_hidden) * factors
    return torch.where(factors == 1.0, hidden, weighted)


def _encode_chunks(
    encoder: Any,
    tokenizer: Any,
    chunks: List[TokenChunk],
    chunk_count: int,
    device: Any,
    *,
    penultimate: bool,
) -> Tuple[Any, Any]:
    import torch

    chunks = chunks + [_chunk(tokenizer, [], [])] * (chunk_count - len(chunks))
    empty_hidden, _ = _encode_chunk(encoder, _chunk(tokenizer, [], []), device, penultimate=penultimate)
    hidden_parts = []
    first_pooled = None
    for chunk in chunks:
        hidden, pooled = _encode_chunk(encoder, chunk, device, penultimate=penultimate)
        hidden_parts.append(_apply_weights(hidden, empty_hidden, chunk.weights))
        if first_pooled is None:
            # ComfyUI takes the pooled vector of the first chunk.
            first_pooled = pooled
    return torch.cat(hidden_parts, dim=1), first_pooled


def _execution_device(pipe: Any) -> Any:
    return getattr(pipe, "_execution_device", None) or getattr(pipe, "device", None) or "cpu"


def _forces_zero_negative(pipe: Any) -> bool:
    config = getattr(pipe, "config", None)
    if config is None:
        return False
    if hasattr(config, "get"):
        return bool(config.get("force_zeros_for_empty_prompt", False))
    return bool(getattr(config, "force_zeros_for_empty_prompt", False))


def encode_prompts(pipe: Any, prompt: str, negative_prompt: Optional[str]) -> EncodedPrompt:
    """Embeddings of the whole prompt and negative prompt for an SD 1.x or SDXL pipeline.

    Raises when the pipeline has no CLIP tokenizer / text encoder; the caller
    then passes the prompt as a string.
    """
    import torch

    second_encoder = getattr(pipe, "text_encoder_2", None)
    is_sdxl = second_encoder is not None
    encoders = [(getattr(pipe, "tokenizer", None), getattr(pipe, "text_encoder", None))]
    if is_sdxl:
        encoders.append((getattr(pipe, "tokenizer_2", None), second_encoder))
    if any(tokenizer is None or encoder is None for tokenizer, encoder in encoders):
        raise ValueError("pipeline has no CLIP tokenizer and text encoder to encode the prompt")

    device = _execution_device(pipe)
    positive = parse_weighted_prompt(prompt)
    negative = parse_weighted_prompt(negative_prompt)
    tokenized = [(tokenize_weighted(tokenizer, positive), tokenize_weighted(tokenizer, negative)) for tokenizer, _ in encoders]
    chunk_count = max(max(len(pos_chunks), len(neg_chunks)) for (pos_chunks, _), (neg_chunks, _) in tokenized)

    prompt_parts: List[Any] = []
    negative_parts: List[Any] = []
    pooled = negative_pooled = None
    with torch.no_grad():
        for (tokenizer, encoder), ((pos_chunks, _), (neg_chunks, _)) in zip(encoders, tokenized):
            # SD 1.x conditions on the final layer; SDXL on the penultimate layer of both encoders.
            pos_hidden, pos_pooled = _encode_chunks(encoder, tokenizer, pos_chunks, chunk_count, device, penultimate=is_sdxl)
            neg_hidden, neg_pooled = _encode_chunks(encoder, tokenizer, neg_chunks, chunk_count, device, penultimate=is_sdxl)
            prompt_parts.append(pos_hidden)
            negative_parts.append(neg_hidden)
            if encoder is second_encoder:
                pooled, negative_pooled = pos_pooled, neg_pooled

    prompt_embeds = torch.cat(prompt_parts, dim=-1)
    negative_embeds = torch.cat(negative_parts, dim=-1)
    if is_sdxl and not (negative_prompt or "").strip() and _forces_zero_negative(pipe):
        negative_embeds = torch.zeros_like(negative_embeds)
        negative_pooled = torch.zeros_like(negative_pooled)

    weighted_segments = sum(
        1 for part, weight in (*positive, *negative) if part.strip() and abs(weight - 1.0) > 1e-9
    )
    return EncodedPrompt(
        prompt_embeds=prompt_embeds,
        negative_prompt_embeds=negative_embeds,
        pooled_prompt_embeds=pooled,
        negative_pooled_prompt_embeds=negative_pooled,
        prompt_tokens=tokenized[0][0][1],
        negative_tokens=tokenized[0][1][1],
        chunks=chunk_count,
        weighted_segments=weighted_segments,
    )

"""Core image generation sees the whole prompt and its weights.

Found 2026-09-12: generating through diffusers, a 206-token prompt was cut to
the 77 tokens a CLIP encoder sees, and weights like "(worst quality:2)" reached
the model as plain text. ComfyUI had encoded both; core now does it itself.

Text encoders here are tiny fakes: the tests check the mechanism (chunking,
weights, SDXL's second encoder), not image quality.
"""

import re

import pytest
import torch
from PIL import Image

from modules.synthesis import prompt_encoding
from modules.synthesis.prompt_encoding import (
    encode_prompts,
    parse_weighted_prompt,
    tokenize_weighted,
)
from modules.synthesis.providers import diffusers_generic
from modules.synthesis.providers.diffusers_generic import DiffusersGenericProvider
from modules.synthesis.types import ImageGenerationRequest, SynthesisModelInfo
from modules.system.logger import AuditStatus

pytestmark = pytest.mark.regression

# A long weighted negative prompt, as one is stored in synthesis.prompting.
SAMPLE_NEGATIVE = (
    "score_4_up, score_5_up, score_6_up, sketch, duplicate, ugly, huge eyes, text, logo, "
    "monochrome, worst face, (bad and mutated hands:1.3), (worst quality:2)"
)
LONG_PROMPT = " ".join(f"word{index}" for index in range(206))


class FakeTokenizer:
    """Word-level stand-in for a CLIP tokenizer."""

    bos_token_id = 1
    eos_token_id = 2
    pad_token_id = 0

    def __init__(self):
        self.vocab = {}

    def tokenize(self, text):
        return re.findall(r"[^\s,]+|,", text.lower())

    def convert_tokens_to_ids(self, tokens):
        return [self.vocab.setdefault(token, len(self.vocab) + 3) for token in tokens]


class FakeEncoderOutput:
    def __init__(self, first, hidden_states):
        self._first = first
        self.hidden_states = hidden_states

    def __getitem__(self, index):
        return (self._first,)[index]


class FakeTextEncoder:
    """Deterministic encoder: every token also depends on the whole chunk, like a transformer."""

    def __init__(self, dim, with_projection=False):
        self.dim = dim
        self.with_projection = with_projection

    def __call__(self, input_ids, output_hidden_states=False):
        frequencies = torch.arange(1, self.dim + 1, dtype=torch.float32)
        tokens = torch.sin(input_ids.to(torch.float32).unsqueeze(-1) * frequencies * 0.37)
        penultimate = tokens + tokens.mean(dim=1, keepdim=True)
        last = penultimate * 2.0
        first = penultimate.mean(dim=1) if self.with_projection else last
        return FakeEncoderOutput(first, (tokens, penultimate, last))


class FakePipeline:
    _execution_device = "cpu"

    def __init__(self, *, sdxl, force_zeros=True, with_tokenizer=True):
        self.tokenizer = FakeTokenizer() if with_tokenizer else None
        self.text_encoder = FakeTextEncoder(8)
        if sdxl:
            self.tokenizer_2 = FakeTokenizer()
            self.text_encoder_2 = FakeTextEncoder(12, with_projection=True)
        self.config = {"force_zeros_for_empty_prompt": force_zeros}
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return type("Output", (), {"images": [Image.new("RGB", (8, 8))]})()


def _plain_chunk_encoding(tokenizer, encoder, text, *, penultimate):
    ids = tokenizer.convert_tokens_to_ids(tokenizer.tokenize(text))
    chunk = [1, *ids, 2] + [0] * (75 - len(ids))
    output = encoder(torch.tensor([chunk]), output_hidden_states=True)
    return output.hidden_states[-2] if penultimate else output[0]


# --- weights --------------------------------------------------------------


def test_plain_prompt_is_one_segment_of_weight_one():
    assert parse_weighted_prompt("a cat on a sofa") == [("a cat on a sofa", 1.0)]


@pytest.mark.parametrize(
    "prompt, text, weight",
    [
        ("(worst quality:2)", "worst quality", 2.0),
        ("(smile)", "smile", 1.1),
        ("((smile))", "smile", 1.21),
        ("[blurry]", "blurry", 1 / 1.1),
        ("((hands:1.2))", "hands", 1.32),
    ],
)
def test_weight_syntax(prompt, text, weight):
    [(parsed_text, parsed_weight)] = parse_weighted_prompt(prompt)
    assert parsed_text == text
    assert parsed_weight == pytest.approx(weight)


def test_escaped_and_unmatched_brackets_stay_text():
    assert parse_weighted_prompt(r"logo \(text\)") == [("logo (text)", 1.0)]
    assert parse_weighted_prompt("smile :) ratio 16:9") == [("smile :) ratio 16:9", 1.0)]


def test_weighted_negative_prompt_keeps_its_weights():
    segments = parse_weighted_prompt(SAMPLE_NEGATIVE)
    weights = {text.strip(): weight for text, weight in segments if weight != 1.0}

    assert weights == {"bad and mutated hands": pytest.approx(1.3), "worst quality": pytest.approx(2.0)}
    assert "(" not in "".join(text for text, _ in segments)


# --- chunking -------------------------------------------------------------


def test_a_long_prompt_is_cut_into_full_clip_windows():
    tokenizer = FakeTokenizer()

    chunks, total = tokenize_weighted(tokenizer, parse_weighted_prompt(LONG_PROMPT))

    assert total == 206
    assert len(chunks) == 3
    for chunk in chunks:
        assert len(chunk.token_ids) == 77 and len(chunk.weights) == 77
        assert chunk.token_ids[0] == tokenizer.bos_token_id
    assert chunks[0].token_ids[76] == tokenizer.eos_token_id
    assert chunks[2].token_ids[57] == tokenizer.eos_token_id  # 206 - 150 = 56 tokens, then the end token


def test_weights_stay_on_their_tokens_across_chunks():
    tokenizer = FakeTokenizer()
    prompt = " ".join(f"w{index}" for index in range(80)) + " (glow:1.5)"

    chunks, _ = tokenize_weighted(tokenizer, parse_weighted_prompt(prompt))

    glow_id = tokenizer.vocab["glow"]
    position = chunks[1].token_ids.index(glow_id)
    assert chunks[1].weights[position] == pytest.approx(1.5)
    assert all(weight == 1.0 for index, weight in enumerate(chunks[1].weights) if index != position)


def test_empty_prompt_is_one_empty_window():
    chunks, total = tokenize_weighted(FakeTokenizer(), parse_weighted_prompt(""))

    assert total == 0
    assert len(chunks) == 1 and chunks[0].token_ids[:3] == [1, 2, 0]


# --- encoding -------------------------------------------------------------


def test_sd15_short_prompt_matches_plain_clip_encoding():
    pipe = FakePipeline(sdxl=False)

    encoded = encode_prompts(pipe, "a cat on a sofa", "")

    expected = _plain_chunk_encoding(pipe.tokenizer, pipe.text_encoder, "a cat on a sofa", penultimate=False)
    assert torch.equal(encoded.prompt_embeds, expected)
    assert encoded.pooled_prompt_embeds is None


def test_sd15_long_prompt_reaches_the_model_whole():
    encoded = encode_prompts(FakePipeline(sdxl=False), LONG_PROMPT, "blurry")

    assert encoded.prompt_embeds.shape == (1, 77 * 3, 8)
    assert encoded.negative_prompt_embeds.shape == encoded.prompt_embeds.shape
    assert (encoded.prompt_tokens, encoded.negative_tokens, encoded.chunks) == (206, 1, 3)


def test_a_weight_changes_only_its_own_token():
    pipe = FakePipeline(sdxl=False)

    plain = encode_prompts(pipe, "a red cat", "").prompt_embeds
    weighted = encode_prompts(pipe, "a (red:1.5) cat", "").prompt_embeds

    changed = (plain != weighted).any(dim=-1)[0]
    assert changed.nonzero().flatten().tolist() == [2]  # start token, "a", "red"


def test_sdxl_uses_both_encoders_and_the_first_chunk_pooled_vector():
    pipe = FakePipeline(sdxl=True)

    encoded = encode_prompts(pipe, LONG_PROMPT, SAMPLE_NEGATIVE)

    assert encoded.prompt_embeds.shape == (1, 77 * 3, 8 + 12)
    assert encoded.negative_prompt_embeds.shape == encoded.prompt_embeds.shape
    first_chunk_words = " ".join(f"word{index}" for index in range(75))
    ids = pipe.tokenizer_2.convert_tokens_to_ids(pipe.tokenizer_2.tokenize(first_chunk_words))
    expected_pooled = pipe.text_encoder_2(torch.tensor([[1, *ids, 2]]), output_hidden_states=True)[0]
    assert torch.equal(encoded.pooled_prompt_embeds, expected_pooled)
    assert encoded.weighted_segments == 2


def test_sdxl_empty_negative_follows_the_pipeline_zero_setting():
    zeroed = encode_prompts(FakePipeline(sdxl=True, force_zeros=True), "a cat", "")
    encoded = encode_prompts(FakePipeline(sdxl=True, force_zeros=False), "a cat", "")

    assert not zeroed.negative_prompt_embeds.any() and not zeroed.negative_pooled_prompt_embeds.any()
    assert encoded.negative_prompt_embeds.any()


def test_a_pipeline_without_clip_encoder_is_refused():
    with pytest.raises(ValueError):
        encode_prompts(FakePipeline(sdxl=False, with_tokenizer=False), "a cat", "")


# --- the provider, whole call (smoke) ------------------------------------


def _model(family):
    return SynthesisModelInfo(
        model_id="image_gen_test", label="test", family=family, source="local", installed=True, path="unused", defaults={}
    )


def _request():
    return ImageGenerationRequest(
        prompt=LONG_PROMPT,
        provider="core",
        negative_prompt=SAMPLE_NEGATIVE,
        width=64,
        height=64,
        num_inference_steps=1,
        guidance_scale=5.0,
        persist_output=False,
    )


@pytest.fixture
def generate(monkeypatch):
    events = []
    monkeypatch.setattr(
        diffusers_generic,
        "log_audit_entry",
        lambda event, message, status=None, details=None, **kwargs: events.append((event, status, details or {})),
    )

    def run(pipe, family):
        provider = DiffusersGenericProvider()
        monkeypatch.setattr(provider, "_get_pipeline", lambda model: (pipe, "cpu"))
        monkeypatch.setattr(provider, "_apply_scheduler", lambda *args, **kwargs: None)
        monkeypatch.setattr(provider, "_release_pipeline", lambda *args, **kwargs: None)
        result = provider.generate(_request(), _model(family))
        return result, pipe.calls[-1], events

    return run


def test_sdxl_checkpoint_gets_the_whole_prompt_as_embeddings(generate):
    result, call, events = generate(FakePipeline(sdxl=True), "sdxl-checkpoint")

    assert result.image_bytes
    assert "prompt" not in call and "negative_prompt" not in call
    assert call["prompt_embeds"].shape[1] == 77 * 3
    assert call["pooled_prompt_embeds"] is not None
    [details] = [details for event, _, details in events if event == "synthesis_prompt_encoded"]
    assert (details["prompt_tokens"], details["chunks"], details["weighted_segments"]) == (206, 3, 2)


def test_other_families_still_get_the_prompt_string(generate):
    _, call, events = generate(FakePipeline(sdxl=False), "z-image")

    assert call["prompt"] == LONG_PROMPT
    assert not [event for event, _, _ in events if event.startswith("synthesis_prompt_")]


def test_failed_encoding_falls_back_to_the_string_and_says_so(generate):
    _, call, events = generate(FakePipeline(sdxl=False, with_tokenizer=False), "stable-diffusion-checkpoint")

    assert call["prompt"] == LONG_PROMPT
    [(status, details)] = [(status, details) for event, status, details in events if event == "synthesis_prompt_encoding_failed"]
    assert status == AuditStatus.WARNING
    assert "tokenizer" in details["error"]


def test_every_clip_family_is_listed():
    assert {"stable-diffusion-checkpoint", "sdxl-checkpoint"} <= prompt_encoding.CLIP_PROMPT_FAMILIES

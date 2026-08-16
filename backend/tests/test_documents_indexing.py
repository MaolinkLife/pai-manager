"""§7.3.3 Document indexing — unit tests.

Covers:
  * split_into_chunks: packing, overlap, oversized paragraphs
  * extract_text: txt/cp1251 decode, html tag stripping, unsupported types
  * build_context_block: formatting, budget, sources
  * instructor: knowledge.documents tool block from memory_context
"""

import pytest

from modules.documents import service as documents_service
from modules.documents.extractors import (
    ExtractionError,
    extract_text,
    split_into_chunks,
    supported_for_indexing,
)


# ---------------------------------------------------------------- chunker

def test_chunks_pack_paragraphs_up_to_size():
    text = "\n\n".join(f"параграф {i} " + "слово " * 20 for i in range(6))
    chunks = split_into_chunks(text, chunk_size=400, overlap=50)
    assert len(chunks) > 1
    assert all(len(chunk) <= 400 + 50 for chunk in chunks)


def test_chunks_share_overlap_tail():
    text = ("A" * 350) + "\n\n" + ("B" * 350)
    chunks = split_into_chunks(text, chunk_size=400, overlap=100)
    assert len(chunks) == 2
    assert chunks[1].startswith("A" * 100)


def test_oversized_paragraph_is_split_hard():
    text = "X" * 1000
    chunks = split_into_chunks(text, chunk_size=400, overlap=0)
    assert len(chunks) >= 3
    assert "".join(chunks) == text


def test_empty_text_yields_no_chunks():
    assert split_into_chunks("   \n\n  ", chunk_size=400, overlap=50) == []


# -------------------------------------------------------------- extractors

def test_extract_plain_text_utf8():
    assert extract_text("привет мир".encode("utf-8"), name="a.txt", mime_type="text/plain") == "привет мир"


def test_extract_cp1251_fallback():
    raw = "привет".encode("cp1251")
    assert "привет" in extract_text(raw, name="b.txt", mime_type="text/plain")


def test_extract_html_strips_tags():
    html = b"<html><body><h1>Title</h1><p>Body text</p></body></html>"
    text = extract_text(html, name="page.html", mime_type="text/html")
    assert "Title" in text and "Body text" in text
    assert "<" not in text


def test_unsupported_type_raises():
    with pytest.raises(ExtractionError):
        extract_text(b"\x00\x01", name="image.png", mime_type="image/png")


def test_supported_for_indexing_matrix():
    assert supported_for_indexing("doc.md", "")
    assert supported_for_indexing("doc.pdf", "application/pdf")
    assert supported_for_indexing("noext", "text/plain")
    assert not supported_for_indexing("image.png", "image/png")


# -------------------------------------------------------- context building

def test_build_context_block_formats_sources(monkeypatch):
    matches = [
        {
            "text": "Содержимое первого чанка",
            "similarity": 0.9,
            "collection_id": "c1",
            "collection_name": "Док-станция",
            "file_id": "f1",
            "file_name": "guide.md",
            "chunk_index": 0,
        },
        {
            "text": "Содержимое второго чанка",
            "similarity": 0.8,
            "collection_id": "c1",
            "collection_name": "Док-станция",
            "file_id": "f2",
            "file_name": "notes.txt",
            "chunk_index": 3,
        },
    ]
    monkeypatch.setattr(documents_service, "search", lambda query, **kwargs: matches)

    block = documents_service.build_context_block("вопрос")
    assert block is not None
    assert "[guide.md]" in block["content"]
    assert "[notes.txt]" in block["content"]
    assert [source["file_name"] for source in block["sources"]] == ["guide.md", "notes.txt"]


def test_build_context_block_respects_budget(monkeypatch):
    matches = [
        {
            "text": "A" * 3000,
            "similarity": 0.9,
            "collection_id": "c1",
            "collection_name": "kb",
            "file_id": "f1",
            "file_name": "big.txt",
            "chunk_index": 0,
        },
        {
            "text": "B" * 3000,
            "similarity": 0.8,
            "collection_id": "c1",
            "collection_name": "kb",
            "file_id": "f2",
            "file_name": "second.txt",
            "chunk_index": 0,
        },
    ]
    monkeypatch.setattr(documents_service, "search", lambda query, **kwargs: matches)
    monkeypatch.setattr(
        documents_service,
        "_settings",
        lambda: {
            "enabled": True,
            "chunk_size": 1200,
            "chunk_overlap": 150,
            "top_k": 4,
            "min_similarity": 0.35,
            "max_context_chars": 2400,
        },
    )

    block = documents_service.build_context_block("вопрос")
    assert block is not None
    assert len(block["content"]) <= 2600
    assert len(block["sources"]) == 1


def test_build_context_block_empty_when_no_matches(monkeypatch):
    monkeypatch.setattr(documents_service, "search", lambda query, **kwargs: [])
    assert documents_service.build_context_block("вопрос") is None


# ------------------------------------------------------------- instructor

def test_instructor_renders_knowledge_documents_block():
    from core.instructor import Instructor

    instructor = Instructor()
    messages = instructor._build_dynamic_tool_messages(
        user_message={"id": "m1"},
        memory_context={
            "knowledge_documents": {
                "content": "[guide.md] Фрагмент текста",
                "sources": [{"file_name": "guide.md"}],
            }
        },
    )
    knowledge = [m for m in messages if m.get("name") == "knowledge.documents"]
    assert len(knowledge) == 1
    assert "[guide.md]" in knowledge[0]["content"]


def test_instructor_skips_empty_knowledge_block():
    from core.instructor import Instructor

    instructor = Instructor()
    messages = instructor._build_dynamic_tool_messages(
        user_message={"id": "m1"},
        memory_context={"knowledge_documents": {"content": "", "sources": []}},
    )
    assert not [m for m in messages if m.get("name") == "knowledge.documents"]

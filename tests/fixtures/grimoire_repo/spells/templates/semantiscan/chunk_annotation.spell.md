---
id: semantiscan/chunk_annotation
name: Chunk Annotation
version: 1.0.0
tags: [semantiscan, indexing, annotation]
description: Annotate a code/document chunk for semantic search enrichment.
variables:
  chunk_text:
    type: multiline
    required: true
    ask: "Text chunk to annotate"
  document_id:
    type: string
    required: true
    ask: "Source document ID"
  chunk_index:
    type: integer
    required: true
    ask: "Chunk index within the document"
---

# SYSTEM
You annotate text chunks for semantic search indexing. Output ONLY valid JSON.
No preamble, no markdown fences, no explanation.

# USER
Document: {{ document_id }}, Chunk: {{ chunk_index }}

Text:
{{ chunk_text }}

Return JSON: {"summary": "...", "keywords": [...], "entities": [...], "chunk_type": "code|prose|mixed"}

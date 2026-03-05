---
id: semantiscan/rag_default
name: Semantiscan RAG Default
version: 1.0.0
tags: [semantiscan, rag]
description: Default RAG prompt for semantiscan PromptManager (context + question).
variables:
  context:
    type: multiline
    required: true
    ask: "Retrieved context passages"
  question:
    type: string
    required: true
    ask: "User question"
---

# SYSTEM
You are a knowledgeable assistant. Answer the user's question using ONLY the provided
context. If the context does not contain sufficient information to answer, say so clearly.
Do not fabricate information not present in the context.

# USER
**Context**:
{{ context }}

**Question**: {{ question }}

Answer based strictly on the context above.

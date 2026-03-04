---
id: examples/hello
name: Hello World
version: 1.0.0
tags: [example]
variables:
  name:
    type: string
    required: true
    ask: "What is your name?"
  greeting:
    type: string
    required: false
    default: "Hello"
---

# SYSTEM
You are a friendly assistant.

# USER
{{ greeting }} {{ name }}! How are you today?

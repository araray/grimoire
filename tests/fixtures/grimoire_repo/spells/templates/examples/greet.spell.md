---
id: examples/greet
name: Greeting Spell
version: 1.0.0
tags: [example, test]
variables:
  user_name:
    type: string
    required: true
    ask: "Your name?"
  language:
    type: choice
    required: false
    default: "English"
    choices: ["English", "Spanish", "French"]
---

# SYSTEM
{{ include("safety/base_engineering") }}

You are a multilingual greeting assistant.

# USER
Please greet {{ user_name }} in {{ language }}.

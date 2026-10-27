You are writing one multi-turn test sequence for a benchmark of how an assistant routes messages to its agents: 12 messages that the user (or the email watcher) sends over a few days. Every turn must satisfy these labeling rules, given the conversation so far:

$rules

## Before turn 1

The conversation already covered these threads, and their agents exist with the names shown:

$history_threads

This agent also exists but hasn't come up in the recent conversation:

$aged_threads

## Threads created during the sequence

No agent exists for these until their CREATE turn; after it, the new agent holds that thread:

$new_threads

## Turn plan

$turn_plan

## What to write

For each turn:
- "message": the new message (for an email notification, only the notification body)
- "poke_reply": the assistant's immediate short reply (an acknowledgement before handing work off, or the full answer on a NO_DELEGATION turn)
- "result_text": on delegating turns, what the agent reports back (one or two sentences, concrete details); null otherwise
- "result_reply": on delegating turns, the assistant's short reply to the user about that result; null otherwise

Each turn sees everything before it, including earlier results. Write like real texting: casual, lowercase is fine, no emojis.

Return only JSON: {"turns": [{"turn": 1, "message": "...", "poke_reply": "...", "result_text": "...", "result_reply": "..."}, ...]}

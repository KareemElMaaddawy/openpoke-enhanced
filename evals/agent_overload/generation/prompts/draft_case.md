You are writing one test case for a benchmark of how an assistant routes messages to its agents. The case must satisfy these labeling rules:

$rules

## The case to write

$plan

## Threads available

$threads

## What to write

Write the end of the conversation (the "tail") and the new message.

The tail is a list of exchanges, oldest first. Each exchange is one of:
- {"kind": "delegated", "thread": "<thread_id>", "user": "...", "ack": "...", "result": "...", "reply": "..."}: the user asked for something on that thread, the assistant acknowledged ("ack"), the thread's agent reported "result", and the assistant replied ("reply"). The result is shown as "[SUCCESS] <agent name>: <result>", so don't repeat the agent name inside it.
- {"kind": "chat", "user": "...", "reply": "..."}: small talk answered directly.
- {"kind": "alert", "text": "...", "reply": "..."}: an important-email notification the assistant passed on ("text" is the notification body).

Rules for the tail:
$tail_rules

The new message:
$message_rules

Write like real texting: casual, lowercase is fine, no emojis. The user's words must sound natural, not like a test.

Return only JSON:
{"tail": [...], "message": "<text>", "rationale": "<one sentence: why the label holds under the rules>"}

If the plan can't be written without breaking the labeling rules, return {"error": "<why>"} instead.

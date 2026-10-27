You are building test data for a personal AI assistant that works through the user's email: it finds emails, summarizes them, drafts and sends replies, and sets reminders.

Write $count realistic work threads for the category **$category_description**. They fill a long list of past work, so they should look like typical, everyday requests, varied and clearly different from each other and from the existing topics. Every thread must be something found or done through the user's email or a reminder.

For each thread give:
- "key": "f1", "f2", ... in order
- "topic": a short, specific description that names a concrete entity (a company, person, product or date)
- "opening_request": the user's message asking for it, casual texting style, 5 to 20 words
- "canned_result": what the assistant's worker found or did, one or two sentences with concrete details
- "result_reply": the assistant's short reply to the user, under 20 words

Avoid these existing topics and anything close to them:
$existing_topics

Use fictional but realistic people and companies. Dates fall between September and November 2026. Return only JSON: {"threads": [...]}

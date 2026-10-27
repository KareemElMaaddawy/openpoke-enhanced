You are building test data for a personal AI assistant that works through the user's email: it finds emails, summarizes them, drafts and sends replies, and sets reminders.

Write $count realistic work threads for the category **$category_description**. A work thread is one unit of real work the user asks the assistant to do, such as finding the October AWS invoice, the offsite email thread with Keith, or a reminder to pay rent on Fridays. Every thread must be something found or done through the user's email or a reminder; nothing needs any other app.

For each thread give:
- "key": "c1", "c2", ... in order
- "topic": a short, specific description that names a concrete entity (a company, person, product or date)
- "opening_request": the user's first message asking for it, written casually like a text message (lowercase is fine), 5 to 20 words
- "canned_result": what the assistant's worker found or did, one or two sentences with concrete details (amounts, dates, names, sender addresses), the way a worker reports back
- "result_reply": the assistant's short reply to the user about that result, under 20 words
- "follow_ups": exactly 3 later requests on the same thread, each {"request", "result", "reply"} in the same style, for example "was that paid already?", "forward it to my accountant", "move the reminder to 7am"
- "pair_key": the key of its near-distractor partner, or null

Near-distractor pairs: exactly $pairs pairs of threads must be near-distractors of each other. The two members share an obvious keyword, brand or person but are different work, for example Uber rides receipts versus an Uber Eats refund, or the offsite thread with Keith versus Keith's performance review. Set each member's "pair_key" to the other's key. Every other thread has "pair_key": null and must be clearly distinct from all the others.

Avoid these existing topics and anything close to them:
$existing_topics

Use fictional but realistic people and companies. Dates fall between September and November 2026. Return only JSON: {"threads": [...]}

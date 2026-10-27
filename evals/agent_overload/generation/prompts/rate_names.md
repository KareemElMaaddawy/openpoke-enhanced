Rate how descriptive each assistant agent name is for the work it was created for.

- "specific": the name identifies both the entity (company, person, product) and the task.
- "partial": the name identifies one of the two.
- "generic": it identifies neither, for example "Email Helper" or "Task Agent".

Items, one JSON object per line:
$items

Return only JSON: {"ratings": [{"agent_id": "...", "rating": "specific" | "partial" | "generic"}, ...]} with one rating per item.

Label the routing of the new message in the input below, following the rules above. The input is exactly what the interaction agent sees.

Return only JSON, with no other text:

{"label": "REUSE" | "REUSE_ANY" | "CREATE" | "NO_DELEGATION", "agents": ["<exact agent name>", ...], "reason": "<one sentence>"}

- REUSE: exactly one agent. REUSE_ANY: every acceptable agent (two or more). CREATE and NO_DELEGATION: an empty list.
- Copy agent names exactly as they appear in <active_agents>.

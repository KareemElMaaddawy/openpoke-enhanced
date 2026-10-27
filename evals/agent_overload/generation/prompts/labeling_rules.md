# Routing labeling rules

These rules decide how an assistant's interaction agent should route one incoming message.

How routing works: the interaction agent talks to the user and hands work to execution agents with `send_message_to_agent(agent_name, instructions)`. Using an existing agent's exact name reuses that agent, which keeps its memory of earlier work. Any other name creates a new agent. Every agent has the same tools (the user's email and reminders); agents differ only in their name and their history.

What the interaction agent sees: the conversation history (user messages, its own replies, and result lines such as `[SUCCESS] AWS Invoice Lookup: Found the invoice...`, possibly after a summary of older conversation), the list of agent names, and the new message. It never sees descriptions of agents or which agent did which work, except through result lines and the summary. Its instructions say to prefer a relevant existing agent over a new one unless the tasks can run in parallel; for example, if an agent found an email and the user wants to reply to it, the reply goes to that agent even if its name doesn't fit the new task.

Choose exactly one label:

1. **REUSE(T)**: the message continues T's work, acting on what T found or made or following up on T's email or trigger, and T is identifiable from what the interaction agent sees (a result line, the summary, or an unambiguous agent name). If T isn't identifiable, the case must not be written.
2. **REUSE_ANY(T1, T2, ...)**: two or more agents visibly hold enough context, for example two agents that both reported the same email. Any of them is acceptable.
3. **CREATE**: the work isn't covered by any agent's visible work, so a new agent is needed. Cases where "a new agent in parallel" is equally valid must not be written.
4. **NO_DELEGATION**: the message is answerable from visible context, is small talk, or is an agent message that only needs summarizing for the user.
5. Cases where asking the user a question is the only sensible response must not be written.

Notes:
- An agent name counts as identifying a thread when it clearly names that same work. An agent for similar-looking but different work (Uber rides versus an Uber Eats refund) is a different thread.
- An important-email notification only needs summarizing (NO_DELEGATION), unless the user earlier asked an agent to act when that email arrived; then it goes back to that agent (REUSE).
- An execution result only needs summarizing (NO_DELEGATION), unless the user asked for a follow-up once that work was done; then the follow-up goes back to the same agent (REUSE).

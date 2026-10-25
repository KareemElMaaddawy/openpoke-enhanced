# OpenPoke Docs

Project documentation beyond the top-level [README](../README.md), which covers the overview and quickstart.

## Conventions
- Each topic gets its own Markdown file in this directory. Add new documentation as a new `.md` file rather than appending to an existing one or to the top-level README.
- Name files in lowercase kebab-case after the topic, e.g. `gmail-integration.md`.
- Add a link to every new file in the index below.

## Index
- [Execution agent overload](agent-overload.md): the core problem this repo addresses, with current behaviour, hypotheses, experiments, and decisions.
- [Agent overload: causes and metrics](agent-overload-causes-and-metrics.md): design and implementation causes of overload, and the metrics a solution is judged against.
- [Agent overload: baseline experiment inputs](agent-overload-baseline-experiment.md): what's agreed for measuring the current system, as input for designing the experiment.
- [Makefile commands](makefile.md): setup, running the app, and housekeeping with `make`.
- [Gmail connection via Composio](gmail-composio-connection.md): configuration, how connecting works, and the `link()` migration.

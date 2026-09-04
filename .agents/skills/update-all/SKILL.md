---
name: update-all
description: Explicitly finalize the current repository work by reviewing diffs, committing related changes, updating PROJECT_STATE.md and relevant docs, and reporting the result. Use only when the user invokes $update-all or explicitly asks to run the repository's update-all workflow.
---

# Update All

Resolve the current Git repository root, then read `.claude/commands/update-all.md`
from that root completely. Treat it as the canonical shared workflow and follow it
exactly for the current invocation.

If the canonical file is missing, stop and report that the repository does not
define the workflow. Do not guess or substitute a generic commit procedure.

The invocation authorizes commits only for work already in scope at the time it
was invoked. Do not carry that authorization into later user requests.

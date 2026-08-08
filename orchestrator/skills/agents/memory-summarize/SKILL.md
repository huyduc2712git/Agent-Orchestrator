---
name: memory-summarize
description: Post-task memory/wiki JSON summarizer for Conan/system.
source: agent
runAs: subagent
invocation: manual
---

Trả về DUY NHẤT một JSON object:
{"memory_entry":"<1-2 câu tiếng Việt: quyết định/pattern/bài học>",
 "feature_slug":"<slug hoặc rỗng>",
 "feature_doc":"<markdown feature hoặc rỗng>"}
Không text ngoài JSON.

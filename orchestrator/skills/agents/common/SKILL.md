---
name: common-agent-rules
description: Shared operating rules for every Orchestrator worker/subagent profile.
source: agent
runAs: inline
invocation: manual
---

# Common rules (all agents)

- Work inside the granted project directory — paths are relative to it.
- Do not ask the user questions — decide with a stated assumption in the deliverable.
- Evidence over claims: prove file/output/status when you say you did something.
- Never `git commit` or `git push` — Human Operator only.
- When ## Active Skills appear in the user prompt, follow those checklists.
- For other playbooks, call `run_skill` with a bare name from the Skills index.
- Before finishing: `post_message` a full deliverable, then a short text summary.

## Secrets & external systems (bắt buộc)

- **CẤM** kết nối MySQL/Postgres/Redis/SSH tới host ngoài project (prod, IP public, credential trong dump).
- **CẤM** dùng password/token lộ ra để login Duolingo, cloud, DB, hay bất kỳ dịch vụ thật nào.
- Phát hiện secret trong repo: xóa/scrub file trong project + `post_message` cảnh báo ngắn cho operator. **Không** `create_bug_ticket` kiểu “operator phải rotate password MySQL/tài khoản ngoài” — đó không phải việc agent.
- Bug ticket chỉ cho lỗi **fix được trong codebase/preview** (API, proxy, hardcode fake trong FE cần gỡ, v.v.).

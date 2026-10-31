---
title: OWASP Top 10 for LLM Applications (2025) for review
source: OWASP Top 10 for Large Language Model Applications, version 2025 (genai.owasp.org)
version: OWASP Top 10 for LLM Applications 2025 (LLM01:2025 to LLM10:2025)
reviewed: 2026-10
---

## Scope

Review of code that calls, hosts, or wraps large language models: prompt construction, retrieval pipelines, tool or function calling, agents, output handling, model and data supply, and cost controls. Apply when the diff imports an LLM SDK, calls a model endpoint, builds prompts from external content, or grants a model the ability to take action.

Classic web issues in the same code (injection, access control, secrets) still apply and are covered by the other topic files. This file covers the LLM-specific risks.

## Rules

### SEC-LLM-001 — LLM01:2025 Prompt Injection

- **Look for:** untrusted text (user input, retrieved documents, web pages, emails, tool output) concatenated into prompts with instructions; model output used to decide tool calls without a policy check; system prompts that rely on the model to refuse.
- **Direct and indirect:** direct from the user; indirect via content the model reads.
- **Why it matters:** the model can be steered to exfiltrate data or misuse tools granted to it.
- **Evidence:** the prompt template, the untrusted source, and the tool or data the model can reach.
- **Mitigations to check:** separation of trusted and untrusted content, least-privilege tools, confirmation for side-effecting actions, output filtering, and no reliance on prompt wording as a security boundary.
- **Default severity:** high when tools or sensitive data are reachable; medium otherwise.
- **CWE:** CWE-74, CWE-77 (in tool execution), CWE-1427 for prompt injection weakness.

### SEC-LLM-002 — LLM02:2025 Sensitive Information Disclosure

- **Look for:** personal data, secrets, or other tenants' data placed in prompts or retrieved context without need; model responses returned without filtering; logging of full prompts and completions containing personal data.
- **Evidence:** what enters the prompt and what the response can reveal.
- **Default severity:** high for secrets or other tenants' data; medium for personal data.
- **CWE:** CWE-200, CWE-359, CWE-532.

### SEC-LLM-003 — LLM03:2025 Supply Chain

- **Look for:** models, adapters, datasets, or embeddings loaded from unverified sources; model files loaded with unsafe formats (for example pickled objects) without isolation; third-party plug-ins with broad permissions; unpinned model versions.
- **Evidence:** the model identifier or file source and the loader.
- **Default severity:** high for unsafe model formats loaded from untrusted sources.
- **Detail:** `supply-chain-ssdf-slsa.md`, `deserialisation.md`.

### SEC-LLM-004 — LLM04:2025 Data and Model Poisoning

- **Look for:** training or fine-tuning pipelines that ingest unvetted user-contributed data; retrieval indexes updated from untrusted sources without review.
- **Evidence:** the ingestion path and whether the source is trusted.
- **Default severity:** medium; high for shared indexes used by many users.

### SEC-LLM-005 — LLM05:2025 Improper Output Handling

- **Look for:** model output inserted into HTML, SQL, shell commands, file paths, or URLs without encoding or validation; model output executed as code; markdown rendering of model output without sanitisation.
- **Why it matters:** the model's output is untrusted input to the next component.
- **Evidence:** the output variable and the sink.
- **Good:** treat output as user input; encode for the sink; never pass to a shell.
- **Default severity:** high; critical if executed.
- **CWE:** CWE-79, CWE-78, CWE-94, CWE-89 by sink.

### SEC-LLM-006 — LLM06:2025 Excessive Agency

- **Look for:** tools with write, delete, payment, or messaging capability given to the model without per-action authorisation; tools acting with a shared service credential instead of the user's permissions; no human approval for irreversible actions; unlimited iteration of agent loops.
- **Evidence:** the tool definition, its permissions, and the credential it uses.
- **Good:** narrow tool scopes, act with the end user's identity, require confirmation for side effects, cap steps and budgets.
- **Default severity:** high to critical for side-effecting tools.
- **CWE:** CWE-250, CWE-269, CWE-862.

### SEC-LLM-007 — LLM07:2025 System Prompt Leakage

- **Look for:** system prompts that contain secrets, credentials, internal URLs, or access rules that the application relies on to stay secret; prompt text returned on request.
- **Why it matters:** system prompts are not a secure store. Assume they can be extracted.
- **Default severity:** high when the prompt holds credentials; low otherwise.
- **CWE:** CWE-200, CWE-522.

### SEC-LLM-008 — LLM08:2025 Vector and Embedding Weaknesses

- **Look for:** retrieval that does not filter by the user's permissions, so documents from other users or tenants can be returned; embedding stores shared across tenants without namespace isolation; uploads ingested into the index without content checks.
- **Evidence:** the retrieval query and the metadata filter applied.
- **Good:** enforce authorisation at retrieval time using the caller's identity, and partition indexes by tenant.
- **Default severity:** high for cross-tenant retrieval.
- **CWE:** CWE-639, CWE-862.

### SEC-LLM-009 — LLM09:2025 Misinformation

- **Look for:** model output presented as authoritative without source attribution or uncertainty; automated decisions (financial, medical, legal) taken on model output without review.
- **Default severity:** medium; high when decisions are automated with real-world effect.

### SEC-LLM-010 — LLM10:2025 Unbounded Consumption

- **Look for:** no limits on tokens per request, requests per user, or spend; agent loops without a step budget; user input that can expand into very large prompts; no timeouts on model calls.
- **Why it matters:** denial of service and runaway cost.
- **Good:** per-user quotas, maximum input and output tokens, timeouts, circuit breakers, and budget alerts.
- **Default severity:** medium; high for unauthenticated access to paid models.
- **CWE:** CWE-400, CWE-770.

## How to apply in review

1. Identify every model call in the diff, its inputs, its outputs, and the tools it can use.
2. Trace untrusted content into prompts and model output into sinks.
3. Check tool permissions and the credential each tool uses.
4. Cite the prompt builder or tool definition by file and line.
5. Do not assert a prompt-injection exploit without describing the instruction path. Mark as medium confidence when the path is plausible but unproven.

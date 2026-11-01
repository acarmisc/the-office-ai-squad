---
title: Server-side request forgery (SSRF) and path traversal
source: OWASP Server Side Request Forgery Prevention Cheat Sheet; OWASP Input Validation Cheat Sheet; OWASP Top 10:2025 A01 (SSRF folded into Broken Access Control); CWE-918, CWE-22
version: OWASP Top 10:2025 A01; OWASP API Security Top 10:2023 API7
reviewed: 2026-10
---

## Scope

Server-side requests to destinations influenced by a caller (SSRF), and file system access with paths influenced by a caller (path traversal, including archive extraction). Applies to webhooks, URL fetchers, image and document processors, importers, file download and upload handlers, and any code that joins a user value to a file path.

## Rules

### SEC-SSRF-001 — User-influenced URL fetched by the server

- **Look for:** `fetch`, `axios`, `HttpClient`, `URL.openStream`, `RestTemplate`, `WebClient`, `curl`, or image and PDF renderers called with a URL or host from the request, a stored field, or a message.
- **Why it matters:** the server can reach internal networks, localhost services, and cloud metadata endpoints (CWE-918, rank 22 in the CWE Top 25 2025).
- **Evidence:** the source of the URL, the request call, and the network the server can reach.
- **Default severity:** high; critical when cloud metadata or internal admin services are reachable.

### SEC-SSRF-002 — Allowlist destinations

- **Look for:** blocklists of hosts or IPs as the only control; checks performed on the hostname string without resolution.
- **Good:** allow only known hosts or patterns (exact host match, scheme `https`, port set), and resolve the name once and connect to the checked address.
- **Why it matters:** blocklists miss alternative encodings, DNS rebinding, and redirects.
- **Default severity:** high when the allowlist is missing for a fetcher.

### SEC-SSRF-003 — Resolve, check, and pin the address

- **Look for:** code that validates the resolved IP and then makes a second request that resolves again; DNS rebinding paths; checks that do not cover IPv6, link-local (`169.254.0.0/16`), loopback, private ranges, or IPv4-mapped IPv6 addresses.
- **Good:** resolve the host, validate every resolved address against a denylist of private, loopback, link-local, and metadata ranges, then connect to that address with the original `Host` header.
- **Default severity:** high.

### SEC-SSRF-004 — Redirects are re-validated or disabled

- **Look for:** HTTP clients that follow redirects by default when the first URL was validated; a validated host redirecting to an internal address.
- **Good:** disable automatic redirects, or validate each hop.
- **Default severity:** high.

### SEC-SSRF-005 — Response handling

- **Look for:** full response bodies returned to the caller (data exfiltration channel); error messages that reveal internal status or content; no size or time limit.
- **Good:** return only the needed fields; cap size and time; do not echo internal error bodies.
- **Default severity:** medium to high.

### SEC-SSRF-006 — Schemes and protocol handlers

- **Look for:** fetchers that accept `file://`, `gopher://`, `dict://`, `ftp://`, or `jar:` URLs (Java `URL` accepts several by default).
- **Good:** allow only `https` (and `http` if required); reject others.
- **Default severity:** high.

### SEC-PATH-001 — Path built from user input

- **Look for:** `new File(base, input)`, `Paths.get(base, input)`, `path.join(base, input)`, `fs.readFile(userPath)`, `sendFile` or static file handlers with request-derived names.
- **Why it matters:** `../` sequences escape the intended directory (CWE-22, rank 6 in the CWE Top 25 2025).
- **Good:** normalise the joined path and confirm it starts with the canonical base directory; reject absolute input; or map input to a server-generated name.
- **Bad:** `fs.readFileSync(path.join(UPLOAD_DIR, req.params.name))`
- **Good:** `const p = path.resolve(UPLOAD_DIR, name); if (!p.startsWith(path.resolve(UPLOAD_DIR) + path.sep)) throw ...`
- **Default severity:** high.

### SEC-PATH-002 — Canonicalisation and symbolic links

- **Look for:** containment checks on non-canonical paths; checks before symlink resolution; checks that compare strings without a trailing separator (`/data` matches `/data-evil`).
- **Good:** use `realpath` or `toRealPath` before the containment check and compare with a separator.
- **Default severity:** medium to high.

### SEC-PATH-003 — Archive extraction (Zip Slip)

- **Look for:** extraction of ZIP, TAR, or JAR entries where entry names are joined to the target directory without checks; absolute names and `..` entries accepted.
- **Good:** resolve each entry, confirm containment, reject links that point outside, cap total size and entry count.
- **Default severity:** high.

### SEC-PATH-004 — Uploaded file names

- **Look for:** stored file names taken from the client; names used in responses headers without encoding; names that include path separators or null bytes.
- **Good:** store under a generated name; keep the original name as metadata, sanitised.
- **Default severity:** medium.

### SEC-PATH-005 — Filesystem access to secrets and configuration

- **Look for:** file-serving endpoints that can reach configuration, key stores, `.env`, `.git`, or runtime directories.
- **Default severity:** high.

## How to apply in review

1. Find each outbound request call and each file-system call in the diff.
2. Trace the value to a request, message, stored record, or document.
3. Check the destination control (allowlist and address checks) and the path control (containment).
4. Cite the file, line, the source of the value, and the reachable target class (internal, metadata, file system).
5. Do not include working SSRF or traversal payloads in findings. Describe the input class.

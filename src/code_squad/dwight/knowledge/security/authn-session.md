---
title: Authentication, sessions, tokens and authorisation flows
source: OWASP Authentication Cheat Sheet; OWASP Session Management Cheat Sheet; OWASP JSON Web Token Cheat Sheet; OWASP Top 10:2025 A07; OWASP ASVS 5.0 chapters V6 to V10 (edition unverified)
version: OWASP Top 10:2025 A07; OWASP ASVS 5.0 (unverified-edition); RFC 7519 (JWT); RFC 9700 (OAuth 2.0 Security Best Current Practice)
reviewed: 2026-10
---

## Scope

Login flows, password handling, multi-factor authentication, session identifiers and lifecycle, token validation (JWT and opaque tokens), OAuth and OIDC client flows, and the boundary between authentication and authorisation. Object-level authorisation rules are in `owasp-api-top10.md`.

## Rules

### SEC-AUTHN-001 — Brute force and credential stuffing controls

- **Look for:** login, reset, and OTP endpoints without rate limits, lockout or back-off, or CAPTCHA escalation; different error messages for unknown user and wrong password; no alerting on repeated failures.
- **Good:** rate limits per account and per source, progressive delays, uniform responses and timing, and monitoring.
- **Default severity:** high.
- **CWE:** CWE-307, CWE-204.

### SEC-AUTHN-002 — Password storage

- **Look for:** passwords hashed with MD5, SHA-1, SHA-256 without a password KDF, or stored in reversible form; missing or static salts; work factors below current recommendations.
- **Good:** Argon2id (preferred), scrypt, or bcrypt with a work factor set to current guidance and a per-password salt. Verify against the OWASP Password Storage Cheat Sheet at review time.
- **Default severity:** critical for plaintext or reversible storage; high for fast hashes.
- **CWE:** CWE-256, CWE-916, CWE-759.

### SEC-AUTHN-003 — Password policy and reuse

- **Look for:** composition rules instead of length; no check against known breached passwords; no maximum length or a very low one; password hints that reveal the password.
- **Good:** minimum length (at least 8, with a longer recommendation), allow long passphrases, check against breach corpora, and do not force periodic rotation without a compromise signal.
- **Default severity:** medium.

### SEC-AUTHN-004 — Multi-factor authentication for sensitive actions

- **Look for:** privileged, financial, or account-recovery actions that do not require step-up authentication; MFA enrolment that can be bypassed by a single factor; recovery codes stored in plaintext.
- **Default severity:** high.

### SEC-AUTHN-005 — Password reset

- **Look for:** reset tokens that are predictable, long-lived, reusable, or not bound to the account; reset links that leak tokens through Referer headers or logs; reset endpoints that reveal account existence.
- **Good:** random tokens of adequate entropy, short expiry, single use, stored as hashes, and invalidated on password change.
- **Default severity:** high.

### SEC-AUTHN-006 — Session identifier generation and storage

- **Look for:** session ids from predictable generators (sequential ids, timestamps, `Math.random`); session ids in URLs; session data stored client-side without integrity protection.
- **Good:** cryptographically random identifiers of at least 128 bits, delivered in cookies.
- **Default severity:** high.
- **CWE:** CWE-330, CWE-338, CWE-598.

### SEC-AUTHN-007 — Session fixation and rotation

- **Look for:** the session id not regenerated after login, privilege change, or MFA completion; session ids accepted from the query string.
- **Default severity:** high.
- **CWE:** CWE-384.

### SEC-AUTHN-008 — Session expiry and logout

- **Look for:** no idle timeout or absolute timeout for sensitive sessions; logout that clears only the client cookie and leaves the server session valid; long-lived tokens with no revocation path.
- **Default severity:** medium; high for admin sessions.
- **CWE:** CWE-613.

### SEC-AUTHN-009 — JWT validation

- **Look for:** JWT libraries used with `alg: none` allowed; algorithm taken from the token header without an allowlist; HMAC and asymmetric keys confused (accepting an RSA public key as an HMAC secret); missing `exp`, `nbf`, `iss`, `aud` checks; tokens accepted without signature verification (decode only); `kid` header used to load keys from untrusted paths.
- **Good:** verify with a fixed algorithm allowlist and a known key; check `iss`, `aud`, `exp`; short lifetimes.
- **Default severity:** critical when signature checks can be bypassed; high otherwise.
- **CWE:** CWE-347, CWE-345, CWE-613, CWE-1390.

### SEC-AUTHN-010 — Token storage and transport

- **Look for:** tokens in URLs or logs; long-lived refresh tokens in local storage; tokens sent over HTTP; cookies without `HttpOnly`, `Secure`, `SameSite`.
- **Note:** storage in browsers is a trade-off with XSS risk; see `node-react.md` and `xss-csrf.md`.
- **Default severity:** high.
- **CWE:** CWE-598, CWE-614, CWE-1004, CWE-1275.

### SEC-AUTHN-011 — OAuth and OIDC client flows

- **Look for:** authorisation code flow without `state` validation or PKCE for public clients; implicit flow in new code; redirect URIs matched by prefix or wildcard; tokens accepted from the front channel without validation; `aud` not checked at the resource server.
- **Good:** authorisation code with PKCE, exact redirect URI matching, `state` and `nonce` validation, audience checks at each resource server. See RFC 9700 for current guidance.
- **Default severity:** high.
- **CWE:** CWE-601, CWE-352, CWE-346.

### SEC-AUTHN-012 — Authentication bypass by path or header

- **Look for:** auth middleware applied to some routes only; authentication decided by a header (`X-User-Id`, `X-Forwarded-For`) set by the client; trust in internal headers without ingress control; path normalisation mismatches between the gateway and the application.
- **Default severity:** critical.
- **CWE:** CWE-306, CWE-290, CWE-287.

### SEC-AUTHN-013 — Service-to-service credentials

- **Look for:** shared static API keys for internal services with no rotation; keys in source; no per-caller identity; long-lived cloud credentials in CI instead of federated short-lived ones.
- **Good:** workload identity or federated short-lived tokens; per-service credentials with rotation.
- **Default severity:** high.

## How to apply in review

1. Identify the authentication mechanism for each changed endpoint, and where identity comes from.
2. Check token validation against the rules above, not just that a library is present.
3. Check session lifecycle around login, logout, and privilege change.
4. Cite the file, the function that validates credentials or tokens, and the missing control.
5. Never print tokens, keys, or passwords in findings. Report the location only.

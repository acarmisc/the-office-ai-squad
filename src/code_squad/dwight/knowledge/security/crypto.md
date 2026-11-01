---
title: Cryptography usage
source: OWASP Cryptographic Storage Cheat Sheet; OWASP Password Storage Cheat Sheet; OWASP TLS Cheat Sheet; NIST SP 800-38D (GCM); NIST SP 800-63B; OWASP Top 10:2025 A04
version: OWASP Top 10:2025 A04; NIST SP 800-63B (current revision at review date)
reviewed: 2026-10
unverified-edition: true
---

## Scope

Use of cryptographic primitives and protocols in application code and configuration: encryption, hashing, signatures, random numbers, key handling, password storage, and transport security. Does not cover the design of cryptographic protocols or the implementation of primitives. Teams should use vetted libraries and not write their own.

## Rules

### SEC-CRYPTO-001 — Broken or weak algorithms for security purposes

- **Look for:** MD5, SHA-1 (for signatures, certificates, integrity against attackers), DES, 3DES for new designs, RC4, Blowfish with small blocks, RSA with keys below 2048 bits.
- **Good:** AES-GCM or ChaCha20-Poly1305 for symmetric encryption; SHA-256 or SHA-3 for hashing; RSA 2048+ or ECDSA P-256+ or Ed25519 for signatures.
- **Note:** MD5 and SHA-1 for non-security checksums (cache keys, deduplication) are acceptable; state the purpose.
- **Default severity:** high.
- **CWE:** CWE-327, CWE-328.

### SEC-CRYPTO-002 — ECB mode and unauthenticated encryption

- **Look for:** `AES/ECB`, `AES` with default mode in Java (which resolves to ECB in some providers), `CBC` without a MAC, custom MAC-then-encrypt constructions.
- **Good:** AES-GCM with a unique nonce per key, or an authenticated construction from the library.
- **Default severity:** high.
- **CWE:** CWE-327, CWE-325.

### SEC-CRYPTO-003 — Nonces and IVs

- **Look for:** static IVs or nonces; nonces derived from counters that reset; random IVs with GCM where the same key encrypts more than the library allows.
- **Why it matters:** nonce reuse in GCM reveals plaintext relationships and breaks authentication.
- **Default severity:** high.
- **CWE:** CWE-329, CWE-323.

### SEC-CRYPTO-004 — Random number generation

- **Look for:** `Math.random()`, `java.util.Random`, `random.random()` (Python non-secure), `rand()` used for tokens, keys, session ids, nonces, or password reset values.
- **Good:** `crypto.randomBytes` or `crypto.getRandomValues` in JS; `SecureRandom` in Java; `secrets` module in Python.
- **Default severity:** high when used for security tokens.
- **CWE:** CWE-330, CWE-338.

### SEC-CRYPTO-005 — Password hashing

- **Look for:** `SHA-256(password)` or MD5 for passwords; bcrypt with a cost too low for current hardware guidance; PBKDF2 with low iterations; no salt; unsalted hashes.
- **Good:** Argon2id with OWASP-recommended parameters, scrypt, or bcrypt. Confirm parameters against the current OWASP Password Storage Cheat Sheet at review time.
- **Default severity:** critical for unsalted fast hashes on a user database; high otherwise.
- **CWE:** CWE-916, CWE-759, CWE-760.

### SEC-CRYPTO-006 — Hard-coded keys and IVs

- **Look for:** literal keys or IVs in source or configuration; keys derived from constants; keys stored beside the ciphertext.
- **Good:** keys from a key management service or secret store; envelope encryption with rotation.
- **Default severity:** critical for production keys; high otherwise. Report location only.
- **CWE:** CWE-321, CWE-798.

### SEC-CRYPTO-007 — Certificate and hostname validation

- **Look for:** `rejectUnauthorized: false` (Node), `NODE_TLS_REJECT_UNAUTHORIZED=0`, `TrustAllCertificates`, custom `X509TrustManager` accepting all, `HostnameVerifier` returning true, `verify=False` (Python requests), `InsecureSkipVerify: true` (Go).
- **Why it matters:** man-in-the-middle attacks on the connection (CWE-295).
- **Default severity:** high; critical when credentials or personal data are sent over the connection.
- **CWE:** CWE-295, CWE-297.

### SEC-CRYPTO-008 — TLS versions and cipher configuration

- **Look for:** TLS 1.0 or 1.1 enabled; SSL 3.0; weak cipher suites (RC4, NULL, export, CBC-SHA1 in legacy configurations); HSTS missing on public sites.
- **Good:** TLS 1.2 minimum, TLS 1.3 preferred; modern cipher suites from current guidance.
- **Default severity:** medium; high for TLS 1.0 or 1.1 on production endpoints.
- **CWE:** CWE-326, CWE-757.

### SEC-CRYPTO-009 — Sensitive data in transit without encryption

- **Look for:** HTTP calls to services that carry credentials or personal data; plaintext protocols (FTP, Telnet, unencrypted LDAP) in configuration; mixed content.
- **Default severity:** high.
- **CWE:** CWE-319.

### SEC-CRYPTO-010 — Signature verification

- **Look for:** signatures computed but not verified; verification that accepts an unsigned message when a field is missing; signature checks that compare with `==` on secrets (timing leak).
- **Good:** constant-time comparison (`MessageDigest.isEqual`, `hmac.compare_digest`, `crypto.timingSafeEqual`).
- **Default severity:** high.
- **CWE:** CWE-347, CWE-208.

### SEC-CRYPTO-011 — Key length and lifecycle

- **Look for:** keys without rotation; keys shared across environments; no key identifier with ciphertext, making rotation hard.
- **Default severity:** low to medium.

### SEC-CRYPTO-012 — Custom cryptography

- **Look for:** homegrown ciphers, encoding presented as encryption (Base64, XOR, simple substitution), or custom token formats protecting data.
- **Default severity:** high. Encoding is not encryption.
- **CWE:** CWE-327, CWE-916.

## How to apply in review

1. Search the diff for crypto APIs: cipher, digest, MAC, signature, random, TLS configuration.
2. For each, identify the purpose: confidentiality, integrity, authentication, password storage, or non-security use.
3. Check mode, nonce, key source, and verification steps.
4. Cite the call, the algorithm, and the purpose. State the exploit condition in one sentence.
5. Do not report MD5 or SHA-1 used for non-security checksums.

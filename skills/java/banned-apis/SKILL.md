---
name: banned-apis
description: APIs that new code in this project must not use, with the approved replacement.
applies_to:
  - "src/main/java/**"
agents:
  - angela
priority: 20
---

# Banned APIs

- `java.util.Date` and `java.util.Calendar` in new code: use `java.time` types.
- `SimpleDateFormat` in new code: use `DateTimeFormatter`, which is thread-safe.
- `Thread.stop`, `Thread.suspend` and `Thread.resume`: use cooperative cancellation.
- `System.exit` outside the application entry point.
- `e.printStackTrace()`: log through the project logger with the exception attached.
- `Runtime.exec` or `new ProcessBuilder` built from concatenated strings: pass an argument list.
- `MessageDigest.getInstance("MD5")` or `"SHA-1"` for security purposes: use SHA-256 or stronger.

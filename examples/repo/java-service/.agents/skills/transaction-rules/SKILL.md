---
name: transaction-rules
description: Transaction boundaries and side effects in the service layer of the Java service.
applies_to:
  - "src/main/java/**/service/**"
agents:
  - angela
priority: 10
---

# Transaction rules

- Transactions begin in service methods. Read-only queries use `@Transactional(readOnly = true)`.
- Do not call remote HTTP services inside a transaction unless the call has an explicit timeout.
- Publish domain events after commit with `@TransactionalEventListener`, not inside the transactional method.
- Do not catch `RuntimeException` around repository calls to hide a failed write; let the rollback happen.
- Each service method changes one aggregate. Coordinate several aggregates through an event, not one long transaction.

---
name: spring-layering
description: "Spring layering: controllers map HTTP to DTOs, services own transactions, repositories stay behind services."
applies_to:
  - "src/main/java/**"
agents:
  - angela
priority: 10
---

# Spring layering

- Controllers translate HTTP to DTOs and call one service method. They do not inject repositories.
- Entities are never returned from controllers or serialised directly; map them to response DTOs.
- Transactions start at the service layer: `@Transactional` on public service methods, `@Transactional(readOnly = true)` on queries.
- `@Transactional` on private methods or on self-invoked methods has no effect. Flag it when you see it.
- Use constructor injection. Field injection with `@Autowired` makes the dependency graph hard to test.
- Validate request DTOs at the controller boundary with Bean Validation annotations.

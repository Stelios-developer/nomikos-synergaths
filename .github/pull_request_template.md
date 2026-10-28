## Behavior and ownership

What changed, why, and which component owns the behavior?

## Verification actually performed

- [ ] Repository checks, targeted tests and build
- [ ] Tenant/session isolation and cancellation when relevant
- [ ] Failure/recovery and concurrency tests when relevant
- [ ] UI screenshots/accessibility when relevant

Distinguish mocks, isolated integration, real services and hosted CI. Link exact evidence; do not claim production correctness from a passing unit test.

## Operational impact

Document compatible schema/configuration changes, privacy, data retention,
rollout and rollback. Never include real documents, credentials or private logs.

## What and why

<!-- What does this change, and why is it worth the added code? -->

## How I tested it

<!-- Commands you ran, what you tried by hand, and anything you could NOT test (e.g. "emulator only"). -->

## Checklist

- [ ] It follows the rules in [CONTRIBUTING.md](../CONTRIBUTING.md) (no silent data loss, no needless dependency, concerns stay separated)
- [ ] I added or updated tests, including a failure case where it makes sense
- [ ] The tests and linters for what I touched pass (`ruff`, `pytest`, `npm run lint/build/test`, `ctest`, `gradlew testDebugUnitTest`)
- [ ] I updated the docs (`docs/api.md`, guides) if behaviour or an endpoint changed
- [ ] If I changed the database: there is an Alembic migration, and I ran the tests on PostgreSQL
- [ ] No secrets, real addresses or personal data in the change

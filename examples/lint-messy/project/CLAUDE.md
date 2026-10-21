# messy service

FastAPI service with a deliberately untidy agent configuration. It exists so that `agent-forge lint` has something to find: this file is long, two rules below repeat each other, one rule contradicts this file, one hook pipes a download into a shell, and one MCP server is defined but disabled.

## How we work

Always run `pytest -q` before you say a change is done; CI runs the same command and nothing merges red. Use `ruff format` on every file you touch. Keep functions under forty lines and name them after what they return.

## Testing

Write the failing test first, then the smallest change that makes it pass, then refactor with the suite green. Never commit with a red test, and never delete a test to make it pass.

## Reviews

Every change touching auth, input parsing or secrets gets a security review before merge: check injection, authorization and secret handling, and say in the PR what you checked.

## Conventions

Identifiers in English, comments in English, error messages in English. Dates are ISO-8601 in UTC. Money is an integer number of cents, never a float. Prefer plain functions to classes until a class removes real duplication.

## Dependencies

Do not add a dependency without saying why in the PR. Pin versions in `pyproject.toml`. Standard library first, then `fastapi`, then everything else.

## Git

Small commits, imperative subject, body says why. Never force-push a shared branch. Never rewrite history that CI has seen.

## Environment

The API key is read from the `API_KEY` environment variable; never write it into a file. Local settings live in `.env`, which is ignored by git. Placeholders look like `${API_KEY}`.

## Documentation

Every public function has a docstring that says what it returns and when it raises. README stays short: how to run, how to test, where the docs are. Architecture decisions go to `docs/adr/`.

## When unsure

Ask. A question costs a minute; a wrong assumption costs a day. State the assumption you are making when you cannot ask.

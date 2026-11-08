# Support Agent

An internal agent-assist app for support staff, built feature by feature.

Feature 1 is a knowledge agent: staff upload SOP documents, which are indexed in
PostgreSQL + pgvector and answered by a LangGraph tool-calling agent with
citations and human approval.

**Status: milestone M1 (Foundation).** This milestone sets up the project,
settings, a FastAPI skeleton with `GET /health`, and the database schema.
There is no ingestion, retrieval, agent, MCP server or UI yet.

## Repository layout

| Folder | Contents |
|---|---|
| `core/` | Python package `core`: settings, logging, async database layer, ORM models, Alembic migrations |
| `server/` | Python package `server`: the FastAPI app |
| `agents/` | LangGraph agents and workflows (milestone M4) |
| `mcp/` | MCP server, Python package `mcp_server` (later milestone) |
| `client/` | Vite + React app (later milestone) |
| `scripts/` | Repo tooling, such as the pre-commit file check |

The Python packages form one [uv](https://docs.astral.sh/uv/) workspace with a
single `uv.lock` at the root.

## Settings

Every setting is required and none has a default. If any are missing or
invalid, startup fails and lists all of them at once.

| Key | Allowed values |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://<user>:<password>@<host>:<port>/<database>` |
| `EMBEDDING_DIMENSION` | Whole number from 1 to 2000. Fixed in the database when migrations run. |
| `APP_ENV` | `development`, `test` or `production` (`production` turns off `/docs` and `/openapi.json`) |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` |

Settings are read from environment variables, and from a `.env` file in the
current directory if one exists. `.env.example` lists the keys with
placeholders. Never commit a `.env` file.

## Local setup (Windows)

Docker is not used for local development.

### 1. Install the tools

1. **Git:** install from <https://git-scm.com/download/win>.
2. **uv:** in PowerShell, run:
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
   uv installs Python 3.12 for this project automatically.
3. **PostgreSQL 16 or later:** run the EDB installer from
   <https://www.postgresql.org/download/windows/>. Note the password you set
   for the `postgres` superuser. Make sure the installer adds
   `C:\Program Files\PostgreSQL\<version>\bin` to `PATH`, so `psql` works.
4. **Visual Studio Build Tools** with the "Desktop development with C++"
   workload, from <https://visualstudio.microsoft.com/visual-cpp-build-tools/>.
   pgvector needs this to compile.

### 2. Build and install pgvector

Open **"x64 Native Tools Command Prompt for VS"** as Administrator. Replace
`<version>` with your PostgreSQL major version (for example `17`):

```bat
set "PGROOT=C:\Program Files\PostgreSQL\<version>"
cd %TEMP%
git clone --branch v0.8.7 https://github.com/pgvector/pgvector.git
cd pgvector
nmake /F Makefile.win
nmake /F Makefile.win install
```

### 3. Create a database and role

pgvector is not a "trusted" extension, so only a superuser can run
`CREATE EXTENSION vector`. The first migration does this, so the role that
runs migrations must be a superuser.

Run `psql -U postgres` and enter (choose your own password):

```sql
CREATE ROLE support_agent LOGIN SUPERUSER PASSWORD '<choose-a-password>';
CREATE DATABASE support_agent OWNER support_agent;
-- Optional: a separate database for the DB tests. The tests empty it.
CREATE DATABASE support_agent_test OWNER support_agent;
```

### 4. Configure settings

In PowerShell, from the repository root:

```powershell
Copy-Item .env.example .env
notepad .env   # replace every <placeholder> with a real value
```

For example: `DATABASE_URL=postgresql+psycopg://support_agent:<password>@localhost:5432/support_agent`.

### 5. Install, migrate and run

```powershell
uv sync
uv run pre-commit install
uv run alembic -c core/alembic.ini upgrade head
uv run support-agent
```

Then open <http://127.0.0.1:8000/health>. You should see:

```json
{"status": "ok", "database": "reachable", "version": "0.1.0"}
```

`uv run support-agent --host <address> --port <port>` binds elsewhere. To undo
all migrations, run `uv run alembic -c core/alembic.ini downgrade base`.

## Development checks

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -m "not db"
```

Tests marked `db` need a real PostgreSQL + pgvector database. They **fail**
rather than skip if `TEST_DATABASE_URL` is not set. They also downgrade that
database to empty, so never point it at a database you care about:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://support_agent:<password>@localhost:5432/support_agent_test"
uv run pytest
```

Tests never read `.env`. They inject settings through fixtures.

## Pre-commit hooks

`uv run pre-commit install` enables these hooks:

- **Block private paths and document files.** Rejects:
  - `.env` and `.env.*` files, except `.env.example`
  - anything inside a `data/`, `uploads/` or `evals/private/` folder at the repo
    root or directly under a package root (`core/`, `server/`, `agents/`, `mcp/`,
    `client/`), e.g. `server/uploads/`. Deeper folders with these names (for
    example a `data` module inside `src/`) are allowed.
  - `.pdf .doc .docx .odt .rtf .pages` files (any case) outside a `tests/fixtures/` folder
- **ruff** lint (with autofix) and **ruff format**.

## API

- `GET /health` always returns 200 with `{status, database, version}`, where
  `database` is `reachable` or `unreachable`.
- Errors return `{code, message, details, request_id}`, with `code` set to
  `validation_error`, `http_error` or `internal_error`. Clients never see a
  stack trace.
- Every response has an `X-Request-ID` header. A safe incoming value (letters,
  digits, `.`, `_` and `-`, up to 128 characters) is reused; otherwise a new
  UUID is generated.

## License

[MIT](LICENSE)

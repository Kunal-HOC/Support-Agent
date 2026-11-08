# Support Agent

An internal agent-assist app for support staff, built feature by feature.

Feature 1 is a knowledge agent: staff upload SOP documents, which are indexed in
PostgreSQL + pgvector and answered by a LangGraph tool-calling agent with
citations and human approval.

**Status: milestone M2 (Ingestion).**
- M1 set up the project, settings, a FastAPI skeleton with `GET /health`, and
  the database schema.
- M2 turns uploaded SOP files (PDF, DOCX, Markdown) into embedded,
  searchable chunks.

There is no retrieval, agent, MCP server or UI yet.

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
| `UPLOAD_DIR` | Absolute path to an existing, writable folder **outside the repository**. Original uploads are stored here. |
| `MAX_UPLOAD_BYTES` | Whole number, at least 1 (e.g. `10485760` for 10 MiB) |
| `MAX_PAGES` | Whole number, at least 1. PDFs with more pages fail with "page limit exceeded". |
| `SOP_CATEGORIES` | Comma-separated names, no blanks or duplicates (e.g. `IT,HR,Facilities`) |
| `EMBEDDING_PROVIDER` | `openai` |
| `EMBEDDING_MODEL` | An OpenAI embedding model, e.g. `text-embedding-3-small` |
| `OPENAI_API_KEY` | Your OpenAI API key (secret) |
| `EMBEDDING_BATCH_SIZE` | 1 to 2048 texts per embeddings request |
| `CHUNKING_STRATEGY` | `heading` (never crosses a section) or `fixed` (sliding window baseline) |
| `CHUNK_MAX_TOKENS` | Whole number, at least 1 |
| `CHUNK_OVERLAP_TOKENS` | Whole number, at least 0 and less than `CHUNK_MAX_TOKENS` |
| `TOKENIZER_ENCODING` | A tiktoken encoding name, e.g. `cl100k_base` |

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

Create the uploads folder somewhere **outside** the repository, for example:

```powershell
New-Item -ItemType Directory -Force C:\SupportAgentData\uploads
```

and set `UPLOAD_DIR=C:\SupportAgentData\uploads`. The app refuses to start if
the folder is missing, not writable, or inside the repository.

The first time a document is chunked, tiktoken downloads its encoding file from
`openaipublic.blob.core.windows.net` and caches it.

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

Tests never read `.env`. They inject settings through fixtures. Embeddings are
faked by default. Tests that chunk with the real tokenizer read the committed
`core/tests/fixtures/tiktoken/cl100k_base.tiktoken`, so no download is needed.

One opt-in test calls the real OpenAI API. It is skipped unless you run:

```powershell
$env:TEST_OPENAI_API_KEY = "<key>"; $env:TEST_EMBEDDING_MODEL = "text-embedding-3-small"
uv run pytest -m openai --run-openai
```

To regenerate the fictional SOP fixtures, run
`uv run python core/tests/fixtures/sop/generate.py`.

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

## Ingestion (M2)

Upload SOPs through Swagger at <http://127.0.0.1:8000/docs>.

| Endpoint | Purpose |
|---|---|
| `POST /documents` | Multipart `file`, `title`, `category`. Returns 202 `{document_id, version: 1, status: "pending"}`. |
| `PUT /documents/{id}` | Multipart `file`: uploads a new version. Returns 202 with `version: n+1`. |
| `GET /documents?status=&category=` | Lists documents with their latest version's number and status, plus the active chunk count. |
| `GET /documents/{id}` | Detail: versions (number, status, failure_reason, sha256, created_at), the active version, section paths and chunk count. |
| `DELETE /documents/{id}` | Removes the document, its versions, chunks and stored files. Returns 204. |

How it works:

1. **Upload.** The request checks the file's extension and content
   (`.pdf`, `.docx`, `.md`), its size, the title (1–200 characters) and the
   category.
2. **Store.** The original is saved as
   `UPLOAD_DIR/<document_id>/v<version>/original.<ext>`.
3. **Ingest in the background.** The file is parsed and split into chunks;
   the chunks are embedded in batches and stored. The version then becomes
   `indexed`, or `failed` with a reason.
4. **Switch versions.** A new version's chunks become active only once it is
   indexed. The previous version's chunks are then marked inactive (kept, not
   deleted). If a new version fails, the previous one stays active.
5. **Duplicates.** Re-uploading content that matches any non-failed version
   returns 409.
6. **One version at a time.** A new version can't be uploaded while the
   previous one is still pending (409).
7. **Restarts.** Versions left pending when the server stopped are marked
   failed at the next startup.

How headings are found:

- **PDF:** the outline (bookmarks) if it has one; otherwise larger-font lines.
- **DOCX:** paragraphs styled `Heading N`.
- **Markdown:** `#` headings.

Pages are recorded for PDFs only.

PDF parsing uses pdfplumber (MIT).

## API

- `GET /health` always returns 200 with `{status, database, version}`, where
  `database` is `reachable` or `unreachable`.
- Errors return `{code, message, details, request_id}`, with `code` set to
  `validation_error`, `http_error`, `internal_error`, `unsupported_file_type`
  (415), `file_too_large` (413), `duplicate_content` (409), `version_pending`
  (409) or `not_found` (404). Clients never see a stack trace.
- Every response has an `X-Request-ID` header. A safe incoming value (letters,
  digits, `.`, `_` and `-`, up to 128 characters) is reused; otherwise a new
  UUID is generated.

## License

[MIT](LICENSE)

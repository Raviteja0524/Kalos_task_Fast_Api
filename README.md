# FastAPI Assessment — Auth Service + Product Service

Two independent FastAPI microservices. The Auth Service issues JWTs; the Product
Service validates them with the shared HS256 secret — no cross-service DB calls.

| Service | Swagger UI | Port | Backing stores |
|---|---|---|---|
| Auth Service | http://localhost:8001/docs | 8001 | Postgres `auth_db`, Redis db 0 |
| Product Service | http://localhost:8002/docs | 8002 | Postgres `product_db`, Redis db 1 |

**How it runs:** both services and Redis run in Docker (via `docker-compose`);
PostgreSQL runs **on your machine** and the containers reach it through
`host.docker.internal`.

---

## Getting started (fresh clone → running)

### Prerequisites

- **Docker Desktop** (or Docker Engine + Compose v2) — `docker compose version` should work
- **PostgreSQL 14+** installed and running locally on port 5432
  - macOS: `brew install postgresql@16 && brew services start postgresql@16`, or use [Postgres.app](https://postgresapp.com)
  - Verify: `psql -l` should list your databases

### 1. Clone the repo

```bash
git clone <repo-url>
cd Kalos_task
```

### 2. Create the databases and apply the schemas

Each service owns its own database. Create both, then apply the SQL schema files:

```bash
createdb auth_db
createdb product_db

psql -d auth_db    -f auth-service/schema.sql
psql -d product_db -f product-service/schema.sql
```

You should see `CREATE TABLE` / `CREATE INDEX` output with no errors.
(If `createdb`/`psql` aren't on your PATH, they ship with your Postgres install —
on Homebrew: `brew link postgresql@16` or use the full path.)

### 3. Configure environment variables

Copy the example env file and fill it in:

```bash
cp .env.example .env
```

Then edit `.env`:

1. Replace `<user>` in both database URLs with your local Postgres username
   (for Homebrew/Postgres.app this is your macOS username; add `:<password>`
   after the user if your Postgres requires one).
2. Set a real `JWT_SECRET_KEY`:

```bash
openssl rand -hex 32   # paste the output as JWT_SECRET_KEY
```

Keep `host.docker.internal` in the URLs — that's how the containers reach the
Postgres running on your machine.

### 4. Start the stack

```bash
docker compose up --build
```

First build takes a couple of minutes. You're up when the logs show both
services listening:

```
auth-service-1     | INFO: Uvicorn running on http://0.0.0.0:8001
product-service-1  | INFO: Uvicorn running on http://0.0.0.0:8002
```

### 5. Verify

Open both Swagger UIs — they should load and list the endpoints:

- Auth Service → http://localhost:8001/docs
- Product Service → http://localhost:8002/docs

---

## Try it (Swagger)

1. On :8001, `POST /auth/register` with an email + password, then
   `POST /auth/login` → copy the `access_token` from the response
2. Click **Authorize** in Swagger and paste the token
3. `GET /auth/me` to see your user — or take the same token to :8002 and use
   the product endpoints (admin endpoints need an admin role, see below)

### Bootstrapping the first admin

Only a super_admin can promote users, so the first one is created directly in
the database (Postgres runs on your machine, so plain `psql` works):

```bash
psql -d auth_db -c "UPDATE users SET role='super_admin' WHERE email='<your-email>'"
```

Then log in again — the role is embedded in the token, so a fresh token is needed.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Services crash on startup with a connection error to Postgres | Postgres isn't running (`brew services list`), or the user/password in `.env` is wrong. Test from your machine: `psql -d auth_db -c 'select 1'` |
| `relation "users" does not exist` | Schemas weren't applied — rerun step 2 |
| `host.docker.internal` doesn't resolve (Linux) | Add to both services in `docker-compose.yml`: `extra_hosts: ["host.docker.internal:host-gateway"]` |
| Port 8001/8002 already in use | Stop the conflicting process or change the host-side port in `docker-compose.yml` (e.g. `"9001:8001"`) |
| 401 on product-service with a valid-looking token | The two services aren't sharing the same `JWT_SECRET_KEY` — set it once in the root `.env` and restart |
| Changed `.env` but nothing happened | Compose reads it at startup: `docker compose down && docker compose up` |

---

## Running a service without Docker (optional)

Useful for debugging with a local interpreter. You'll need Python 3.13 and a
local Redis (`brew install redis && brew services start redis`).

```bash
cd auth-service                    # or product-service
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # edit: Postgres user + shared JWT_SECRET_KEY
uvicorn app.main:app --port 8001   # product-service uses --port 8002
```

The service-level `.env` points at `localhost` (not `host.docker.internal`)
since nothing is inside a container in this mode.

---

## Project structure

```
.
├── docker-compose.yml        # redis + auth-service + product-service
├── .env.example              # copy to .env — DB URLs + shared JWT secret
├── auth-service/
│   ├── schema.sql            # users table — apply once with psql (step 2)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/                  # routers → auth_service → queries, + models,
│                             #   schemas, auth_context, config, database, main
└── product-service/
    ├── schema.sql            # categories + products tables
    ├── Dockerfile
    ├── requirements.txt
    └── app/                  # same layout, product_service.py as service layer
```

## Architecture notes

- **Flat layout, layered code**: each service is ~9 single-purpose files under
  `app/` (`routers.py` → `auth_service.py`/`product_service.py` → `queries.py`,
  plus `models.py`, `schemas.py`, `auth_context.py`, `config.py`,
  `database.py`, `main.py`). Routes still contain no business logic.
- **Refresh tokens**: each carries a `jti` stored in Redis (`refresh:{jti}`,
  7-day TTL). Rotation and logout delete the key — a deleted/rotated token is
  rejected. `GETDEL` makes rotation atomic under concurrent refresh attempts.
- **Rate limiting**: `login_fail:{email}` counter in Redis, 15-min TTL; 5
  failures → 429 before password verification.
- **Product caching**: `product:{uuid}` in Redis, TTL 300s, `X-Cache: HIT|MISS`
  headers; every product write deletes the key before returning.
- **Stock guard**: single atomic `UPDATE ... WHERE stock_quantity + delta >= 0`
  — concurrent decrements cannot oversell (verified with parallel requests).
- **Errors**: product-service returns RFC 7807-style `{detail, type, status}`
  via global exception handlers.

## Spec deviations (deliberate simplifications)

- Flat `app/*.py` files instead of the spec's `routers/`, `services/`,
  `models/`, `schemas/`, `dependencies/`, `core/` folders (§4) — same layering,
  fewer files, chosen for readability at this project size.
- structlog logging (§2.5) removed from both services by choice.
- Alembic (§2.1, §5) replaced with hand-written `schema.sql` files applied once
  with `psql` during setup (step 2 above) — the app never creates or alters
  tables; Alembic would be the tool the moment schema changes must be applied
  to existing databases.
- Auth-service error responses use FastAPI's default `{detail}` shape (global
  RFC 7807 handlers were removed together with logging).

## Known trade-offs (deliberate)

- **Logout does not kill access tokens** — they stay valid up to 15 minutes.
  Inherent to stateless JWTs; the refresh token is what gets revoked.
- **PUT /products/{id} does not change stock** — stock is managed exclusively
  by `PATCH /products/{id}/stock` so the delta guard can't be bypassed.
- **pytest suite not yet included** — behavior was verified with end-to-end
  smoke tests against the dockerized stack (40 checks across both services);
  the formal pytest + coverage deliverable is the remaining work item.

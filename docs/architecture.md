# Architecture — Apollo Voice AI

## 1. System overview

```
                          ┌─────────────────────────────────────────┐
   Caller ──phone/web──▶  │  Retell  (STT → LLM → TTS, 6 tools)       │
                          └───────────────────┬───────────────────────┘
                                  HTTPS + HMAC signature │ POST {name, args, call}
                                              ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  FastAPI (stateless, async)   ── horizontally scalable behind a LB ──      │
   │   middleware: request-id · latency timer · structured JSON logs            │
   │   routes ──▶ services ──▶ booking_service (FOR UPDATE + partial-unique idx)│
   └───────────────┬──────────────────────────────────┬─────────────────────────┘
        read cache │ (doctors/departments)             │ asyncpg pool
                   ▼                                    ▼
            in-proc TTL cache                  PostgreSQL (source of truth)

   Admin SPA (read-only) ─────▶ FastAPI /admin/*  (separate API-key trust boundary)
```

Two inbound contracts hit the same service layer:
- **`/retell/*`** — what Retell actually calls: a POST envelope `{name, args, call}`.
  The caller's number arrives in `call.from_number` and identifies them for
  lookup/reschedule/cancel.
- **REST** (`GET /doctors`, `POST /appointments`, …) — the documented contract
  used by the eval harness, admin UI, and any future integration.

Both reuse the **same services**, so business logic has exactly one home.

## 2. The double-booking guarantee (the core design decision)

A clinic booker's worst failure is reserving one slot for two patients. We make
that impossible with two independent layers:

1. **Pessimistic lock** — booking does `SELECT … FOR UPDATE` on the slot row, so
   two concurrent bookings on the same slot are serialized: the second waits,
   then sees `is_booked = true` and is offered alternatives.
2. **Database invariant** — a *partial unique index* allows at most one
   `status='booked'` appointment per slot:
   ```sql
   CREATE UNIQUE INDEX uq_appointment_active_slot
   ON appointments (slot_id) WHERE status = 'booked';
   ```
   Even if the lock were ever bypassed (read replica, a future refactor), the
   database physically rejects the second insert. The app converts that
   `IntegrityError` into a graceful "slot taken, here are other times."

**Proven** by `backend/scripts/concurrency_check.py`: 10 simultaneous bookings on
one slot → exactly 1 wins, 9 receive alternatives. No double-booking.

**Idempotency** — a repeated `idempotency_key` (Retell's `call_id` on a retry)
returns the original appointment instead of creating a duplicate.

## 3. Data model (5 tables)

| Table | Role | Notable constraints / indexes |
|---|---|---|
| `departments` | 11 specialties | unique name |
| `doctors` | 14 consultants | FK → department, indexed name |
| `doctor_schedules` | recurring weekly OPD windows | unique (doctor, day, start) |
| `slots` | generated bookable units | unique (doctor, start); composite index `(doctor_id, is_booked, start_time)` for the availability hot path |
| `appointments` | source of truth | **partial unique index** on `slot_id WHERE booked`; index on `patient_phone`; unique `idempotency_key` |

`slots.is_booked` is a denormalized fast-path flag (cheap availability reads +
the lock target); `appointments` is authoritative.

## 4. Scaling path (designed-for, not pre-built)

| Concern | MVP today | At scale |
|---|---|---|
| App tier | stateless async FastAPI; gunicorn + uvicorn workers | add replicas behind a LB — no code change |
| DB connections | tuned asyncpg pool, `pool_pre_ping` | PgBouncer; read replicas for availability reads |
| Read load | in-process TTL cache (`cache.py`) | swap backend to Redis — only `cache.py` changes |
| Schema changes | Alembic migrations | same; zero-downtime discipline |
| Observability | request-id + `latency_ms` JSON logs | ship to Datadog/Grafana; alert on turn latency |
| Multi-clinic | single tenant | add `clinic_id` FK + row-level security |

Deliberately **not** built: Redis, queues, k8s. Each is a swap, not a rewrite —
that restraint keeps the MVP minimal while leaving the seams open.

## 5. Latency

Backend per-call latency is **p50 ≈ 10 ms, p95 ≈ 25 ms** locally (see
`eval/results/latest.json`). That's a rounding error next to Retell's
~600–800 ms STT+LLM+TTS budget — the backend is intentionally never the
bottleneck in a turn. Indexed reads and the cache keep it that way under load.

## 6. Security

- **Retell HMAC** — `/retell/*` and mutating REST routes verify an HMAC-SHA256
  signature over the body (`verify_retell_signature`, constant-time compare).
  Off in dev so the harness runs without a key; on in prod via env.
- **Admin key** — `/admin/*` requires `X-API-Key`; a different credential and
  trust boundary from the voice path.
- **No leaked internals** — the global handler returns speakable error messages,
  never stack traces.

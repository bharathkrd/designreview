# Scaling and cloud deployment

*Written 2026-10-17 in ASD-STE100 (Simplified Technical English) style. This is a plan. The code does not have
these changes yet. [`FIRST_PRINCIPLES.md`](FIRST_PRINCIPLES.md) §9.5 links to this document.*

This document answers two questions. **What must change so that 10,000 users can use the agent at the same
time? How do we deploy it to the cloud?**

The short answer: the domain pack, the allowlist, the claim audit and the grader do not change. The runtime
changes. A run must stop being a CLI process with local files. It must become a job in a shared service, with a
queue, shared caches and shared storage.

---

## 1. The load, in numbers

### 1.1 The assumption

"10,000 users at the same time" does not mean 10,000 questions in each second. This plan assumes that each
active user asks one question every 2 minutes. All the numbers below change linearly with that assumption.

The run figures come from a measured live run of task t01
(`runs/live-llm-openai-first-2026-10-14-t01_battery_tray_rev_diff-suryodaya`):

| Measured value | t01, live |
|---|---|
| Run time | 14.74 s |
| Setup: process start, login, tool catalogue | 3.58 s |
| Platform reads | 6 calls |
| LLM call | 2,618 input tokens, 304 output tokens, 4.73 s |
| LLM cost | $0.000414 |
| CPU work of the agent (simulator, no network) | about 30 ms |

### 1.2 Little's law

Little's law gives the number of runs in progress: L = λ · W. Here λ is the arrival rate and W is the time in
the system.

```
λ (arrival rate)        = 10,000 users / 120 s                 ≈ 83 runs/s
L (runs in progress)    = λ · W = 83 · 14.7 s                  ≈ 1,250 runs at the same time
platform calls          = 6 · 83                               ≈ 500 calls/s to AgentSwitch
LLM input tokens        = 2,618 · 83 · 60                      ≈ 13 million tokens/min
LLM output tokens       = 304 · 83 · 60                        ≈ 1.5 million tokens/min
LLM cost at peak        = $0.000414 · 83 · 3,600               ≈ $124/hour
CPU of the agent        = 0.030 s · 83                         ≈ 2.5 cores
```

### 1.3 What the numbers show

- **Our own CPU is not the limit.** 2.5 cores cost little.
- **The limits are outside our code.** They are the capacity of the AgentSwitch platform, the token limits of
  the LLM providers and the setup cost of each run.
- **A burst needs a queue.** If 10,000 users ask in the same minute, the system must queue the questions. It
  must not start 10,000 processes.

Thus the design rule for scale has four parts. Share what each run repeats. Cache what users repeat. Queue the
rest. Use the template answer when an outside service is slow or full.

---

## 2. What must change in the framework

### 2.1 From a CLI to a service

| Now | Change | Reason |
|---|---|---|
| `batch.py` starts one Python subprocess for each run. | Long-lived worker processes run many runs at the same time. | The process start and the imports then occur once, not 83 times each second. |
| The engine uses threads and blocking I/O. | An `asyncio` engine mode, with async HTTP clients for the platform and the LLMs. | 1,250 runs with 3 parallel reads each need about 3,750 open sockets. Async I/O handles that in a few processes. |
| No API. | An HTTP API: `POST /v1/questions`, `GET /v1/runs/{id}`, and `GET /v1/runs/{id}/events` as a server-sent event stream. | Users need a request, a reply and progress during the 10 to 15 seconds of a run. |
| The user gets the answer at the end. | The stream sends each step: route, reads, verdict. The stream sends LLM text only after the audit passes. | The rule "audit before the user reads it" stays true. |

The pack seam does not change. The `Planner`, `Channel` and `CheckpointSaver` interfaces keep their contracts.
The CLI and CI keep the synchronous path.

### 2.2 Share what each run repeats

| Repeated in each run now | Change |
|---|---|
| Seat login (most of the 3.58 s setup) | Keep a session pool for each tenant in each worker. Refresh the token before it expires. Keep the one re-login on HTTP 401. |
| `tools/list` and the catalogue fingerprint | Cache them for each tenant, for 10 minutes. Run the preflight as a scheduled check, not in each run. |
| The BM25 index of the design standards | Build it once for each tenant and keep it in worker memory. Build it again when a standard changes (`updated_at`) or after a set time. |
| The same read by many users | Add a read-through cache in Redis. The key is (tenant, tool, canonical arguments). The time to live is 30 to 60 seconds. The journal records each cache hit. |
| The same question about the same data | Add a finding cache. The key is a hash of the finding and the normalised question. A hit gives the audited answer again, at no LLM cost. |

Example: a 60% hit rate in the read cache lowers the platform load from 500 to about 200 calls/s. A 50% hit
rate in the finding cache halves the LLM tokens.

### 2.3 Move process state to shared stores

| State | Now | At scale |
|---|---|---|
| Run record, journal, graph, ledger, telemetry | Files in `runs/<id>/` | Postgres for the status, the metadata and the ledger. Object storage for the full run folder. The grader and the viewer still read the same files. |
| Checkpoints | `graph.json`, `JsonlSaver` | A `PostgresSaver` behind the `CheckpointSaver` interface. Then any worker can continue any run. |
| Rate state of each LLM provider | In the process (`RateState`) | A token bucket in Redis for each provider key. A provider limit applies to the key, not to one pod. |
| LLM response cache | In the process (LRU) | Redis, with the same SHA-256 key |
| Cost limit | Each run ($0.25) | Keep it. Add a budget for each user, each tenant and each day, in Redis. Over budget, the template answers. |
| Approval of writes | `interrupt()` and a resume in the same folder | Paused runs in Postgres. An approver continues a run through the API. |

### 2.4 Protect the platform and the providers

1. Put a queue between the API and the workers. A burst waits in the queue, and the API returns HTTP 202 with
   the position.
2. Set a concurrency limit for each tenant and each tool, with a semaphore in Redis. Thus one large tenant
   cannot use all the platform capacity.
3. Share the circuit breaker of each provider in Redis. When all providers are down or over budget, the template
   answers. That answer is still correct, because code calculates the facts.
4. Spread the LLM calls over providers and keys. `routing.toml` already does this. Ask each provider for a
   higher rate tier.
5. Measure the prompt-cache hit rate. The stable prefix is already first in each prompt. Most providers charge
   less for cached input tokens.
6. Shed load above a set queue depth: return HTTP 503 with `Retry-After`. A request must never wait with no
   limit.

### 2.5 Users, identity and security

| Need | Change |
|---|---|
| User login | OIDC or SSO at the API gateway. Each request carries the user and the tenant. |
| Tenant access | The API checks which tenants each user can read. The seat credential stays on the server. |
| Secrets | A cloud secret manager loads the keys when a pod starts. No `.env` file goes into an image. Error text stays scrubbed. |
| Writes (`raise_handoffs`) | Approval through the API. An idempotency key on each write, so that a retry cannot file twice. |
| Audit log | The tool journal of each run, kept append-only in object storage, with a retention time |
| Personal data | Redact it before telemetry export. Set a retention time for each tenant. |
| Abuse | A rate limit for each user and a length limit for each question. The quarantine and the claim audit stay. |

### 2.6 Observability and evaluation in production

- **Telemetry.** Export the existing spans (`on_tool_*`, `on_llm_*`) through OpenTelemetry, with the GenAI
  attribute names.
- **Service levels.** These are the starting targets:
  - API availability: 99.9%.
  - First progress event: less than 1 s at p95.
  - Answer: less than 20 s at p95.
  - Claim-audit pass rate for LLM answers: 95% or more.
  - Template fallback rate: less than 10%.
- **Online evaluation.** A background job sends 1% of live runs to the existing grader: ground truth, checks
  and goldens. An alarm starts when the pass rate falls, when `drift` increases, or when the catalogue
  fingerprint changes.
- **CI.** All current gates stay. A nightly load test against the simulator joins them (§3, step 1).

---

## 3. Cloud deployment, step by step

The example uses AWS. The design does not depend on one cloud:

| AWS | Google Cloud | Azure |
|---|---|---|
| EKS | GKE | AKS |
| SQS | Pub/Sub | Service Bus |
| Aurora PostgreSQL | Cloud SQL | Azure Database for PostgreSQL |
| ElastiCache Redis | Memorystore | Azure Cache for Redis |
| S3 | Cloud Storage | Blob Storage |
| Secrets Manager | Secret Manager | Key Vault |

### 3.1 The target architecture

```
 Users ──► CloudFront + WAF ──► ALB (OIDC login, rate limit)
                                   │
                         ┌─────────▼─────────┐
                         │ API service (EKS) │  POST /questions · GET /runs · event stream
                         │ stateless, async  │  4 to 6 pods, scaled on CPU and requests/s
                         └──┬─────────────┬──┘
                            │ enqueue     │ status and events
                    ┌───────▼──────┐   ┌──▼────────────────────────────┐
                    │ SQS + DLQ    │   │ Redis: caches, rate buckets,  │
                    └───────┬──────┘   │ budgets, locks, event pub/sub │
                            │          └──▲────────────────────────────┘
                 ┌──────────▼───────┐     │
                 │ Agent workers    │─────┘
                 │ (EKS, KEDA scales│──► Aurora Postgres: runs, checkpoints, ledger, sessions
                 │  on queue depth) │──► S3: run folders, append-only audit log
                 └───┬─────────┬────┘
                     │         │  egress through NAT (fixed IP addresses)
             AgentSwitch MCP   LLM providers

 Jobs: grader for sampled runs · index rebuild · catalogue check
 Platform: Secrets Manager · ECR · OpenTelemetry collector → metrics, traces, logs
```

### 3.2 Step 1: measure before you build

1. Write a load driver that sends questions at a set rate to the simulator.
2. Run it with `--skip-llm`. Then run it with a mock LLM transport that waits 4.7 s.
3. Find how many runs one worker process can hold before the p95 latency increases.
4. Agree on a call budget for each tenant with the owners of AgentSwitch.
5. Get the rate tiers in writing from each LLM provider.

The biggest risk is the platform. It must accept about 200 to 500 calls/s from one seat. Confirm this before
you build anything else.

### 3.3 Step 2: change the code

Do these changes in this sequence. Each one can ship alone.

1. Add `agentkit/service/`: the API, the login middleware, idempotency keys and the event stream. This adds two
   dependencies: an ASGI framework and its server.
2. Add `agentkit/worker/`: a queue consumer that calls `run_task` in the same process, with a client pool for
   each tenant.
3. Add async versions of the transport and the gateway. Add an async mode to the engine.
4. Add storage adapters behind the current interfaces: `PostgresSaver`, an object-storage run store, a Redis
   cache and Redis rate state.
5. Add the caches: session, catalogue, index, read-through and finding. Each cache reports its hits and misses.
6. Add the budgets and the shared circuit breakers. The template stays the fallback.
7. Add the OpenTelemetry exporter and the sampler for online evaluation.
8. Add tests: fakes for Postgres and Redis in the unit tests, and a nightly simulator load test in CI.

### 3.4 Step 3: build the container image

1. Use a multi-stage build on `python:3.12-slim`, with a non-root user and a read-only root file system.
2. Pin each dependency with its hash (`pip install --require-hashes`).
3. Put the pack, the plans and the routes into the image.
4. Load `config/*.toml` from a ConfigMap. Then a routing change does not need a new image.
5. Give the image two entry points: `api` and `worker`.
6. Add a liveness check (`/healthz`) and a readiness check (`/readyz`). Readiness examines Redis, Postgres,
   the queue and one tenant session.

### 3.5 Step 4: build the infrastructure as code

1. Make a VPC with private subnets in 3 availability zones. Add NAT gateways with fixed egress IP addresses, and
   VPC endpoints for S3, SQS and Secrets Manager.
2. Make an EKS cluster with two node groups: `api` and `workers`. Workers can use spot instances, because a run
   can continue from its checkpoint.
3. Make Aurora PostgreSQL with a writer and a reader in two zones.
4. Make ElastiCache Redis in cluster mode, with 2 shards and replicas.
5. Make an SQS queue with a dead-letter queue (`maxReceiveCount = 3`).
6. Make two S3 buckets: run folders with a lifecycle rule, and the audit log with Object Lock.
7. Put each LLM key and each seat credential in Secrets Manager. Give each pod an IAM role with the least
   privilege it needs.
8. Put CloudFront, WAF rules and an ALB with OIDC login in front of the API.

### 3.6 Step 5: set the first sizes

Start with these sizes. Then change them with the results of step 1.

| Component | First size | Scales on |
|---|---|---|
| API pods | 4 pods, 1 vCPU and 1 GB each | CPU at 60%, requests each second |
| Worker pods | 10 pods, 2 vCPU and 2 GB each, about 150 runs each: 1,500 run slots | Queue depth and the age of the oldest message (KEDA), up to 40 pods |
| Aurora PostgreSQL | One writer and one reader, `db.r6g.large` | About 1,000 small writes each second. Examine the IOPS. |
| Redis | 2 shards, `cache.r6g.large` | Memory and CPU |
| Queue | SQS standard, visibility timeout 120 s | The visibility timeout must be longer than the run timeout. |

### 3.7 Step 6: set up CI and CD

1. Keep all current CI gates.
2. Add an image build, an image scan and an image signature. Push the image to ECR.
3. Deploy to staging first, with the simulator and a staging tenant on AgentSwitch.
4. Deploy to production as a canary: 5%, then 25%, then 100% of the traffic.
5. Roll back automatically when an SLO fails, when the audit pass rate falls, or when the template fallback
   rate increases.
6. Treat a change to prompts, plans or `routing.toml` as a release. It must pass the graded batch and the
   Pareto report before it merges.

### 3.8 Step 7: make it ready for production

1. Write a run book for each failure:
   - **All LLM providers down:** the template answers.
   - **AgentSwitch slow:** the queue absorbs the load. Then the API sheds load.
   - **Catalogue fingerprint changed:** an alarm starts. Stop the routed tasks that use a changed tool.
   - **Redis down:** bypass the caches and accept slower runs.
2. Set up disaster recovery: Aurora backups with point-in-time restore, S3 versioning, and Terraform for all
   infrastructure. The targets are recovery in 1 hour, with a maximum of 5 minutes of lost data.
3. Do a game day on staging. Inject faults (`fail_always`, a slow LLM, a Redis failover) and make sure that
   each run still ends with a verdict.
4. Set a budget and an alarm for each tenant. Make a daily cost report from the ledger table.

### 3.9 Step 8: roll out in stages

| Week | Users | Goal |
|---|---|---|
| 1 | Shadow traffic | Real questions run. The system records the answers but does not show them. |
| 2 | About 100 internal users | Find usability and latency problems. |
| 3 | 1,000 users | Tune the caches and the worker concurrency. |
| 4 | 10,000 users | Go live when the SLOs and the cost for each question stay in their limits for one week. |

---

## 4. Cost estimate at peak

These numbers are estimates. Measure them in step 1.

| Item | Assumption | Estimate |
|---|---|---|
| LLM | 83 runs/s at peak, $0.000414 each, 8 busy hours each day, 50% finding-cache hits | about $500 each day (about $1,000 with no cache) |
| Compute | About 14 pods on average, spot instances for the workers | about $1,500 to $3,000 each month |
| Data and network | Aurora, Redis, S3, NAT, WAF | about $2,000 to $4,000 each month |

The design already has the levers that lower the LLM cost:

- the template answer at $0;
- the cascade, which tries the cheap model first;
- the stable prompt prefix for provider caches;
- the finding cache;
- the budget for each tenant.

---

## 5. What does not change

- The pack seam and the allowlist of actions.
- Facts in code, and the claim audit of each LLM answer.
- Dry run by default, and approval before each write.
- The grader, the mutants, the replay calibration and the fault matrix.

All the scale work is in the runtime: async I/O, the queue and the storage. The framework already keeps the
domain logic out of `agentkit`, so the change to the runtime does not touch the pack.

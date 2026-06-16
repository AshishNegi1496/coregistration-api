# Coregistration Backend Flow

This is the end-to-end flow of the current FastAPI backend.

```mermaid
flowchart TD
    A[Start app] --> B[Load .env settings]
    B --> C[Read DATABASE_URL and folder roots]
    C --> D[Create SQLAlchemy engine]
    D --> E[Create tables in Postgres]
    E --> F[Start FastAPI on localhost:8000]
    F --> G[Open Swagger at /docs]

    G --> H[User sends request]
    H --> I[FastAPI router]
    I --> J{Endpoint type}

    J --> K[/jobs/process or /jobs/batch-process/]
    J --> L[/scheduler/config or /scheduler/scan/]
    J --> M[/metrics or /system/health/]

    K --> N[Validate target file in TARGET_ROOT]
    K --> O[Find base file in BASE_ROOT]
    K --> P[Create output path in OUTPUT_ROOT]
    N --> Q[Insert job row in Postgres]
    O --> Q
    P --> Q
    Q --> R[Insert job log row]
    R --> S[Return job response in Swagger]

    L --> T[Read or update scheduler rows]
    T --> U[Scan configured folders]
    U --> V[Discover image files]
    V --> W[Save scan time in Postgres]
    W --> X[Return scan result]

    M --> Y[Read job counts from Postgres]
    M --> Z[Return health and path status]

    S --> AA[Client sees job id and status]
    X --> AA
    Z --> AA
```

## What Happens From Start to End

1. You set `DATABASE_URL`, `TARGET_ROOT`, `BASE_ROOT`, and `OUTPUT_ROOT` in `api/.env`.
2. `python -m api.init_db` connects to Postgres and creates the tables.
3. `uvicorn api.main:app` starts the API.
4. Swagger opens at `/docs`.
5. When you call `/jobs/process`, the API:
   - checks the target file in `TARGET_ROOT`
   - finds the base file in `BASE_ROOT`
   - prepares the output path in `OUTPUT_ROOT`
   - stores the job in Postgres
   - stores an initial log row
6. When you call `/scheduler/scan`, the API:
   - reads configured watch folders from Postgres
   - scans them for image files
   - updates scan timestamps
7. When you call `/metrics` or `/system/health`, the API reads live data from Postgres and the local folders.

## Simple Request Flow

```mermaid
sequenceDiagram
    participant U as User
    participant S as Swagger UI
    participant A as FastAPI
    participant D as Postgres
    participant F as File System

    U->>S: Open /docs
    U->>S: POST /jobs/process
    S->>A: Send request JSON
    A->>F: Check target/base/output folders
    A->>D: Insert job row
    A->>D: Insert log row
    D-->>A: Commit success
    A-->>S: Return job response
    S-->>U: Show job id and status
```

## Folder Role

- `TARGET_ROOT`: where incoming target images live
- `BASE_ROOT`: where reference/base images live
- `OUTPUT_ROOT`: where generated output files are written
- `STAGING_ROOT`: optional temporary working area
- `LOG_ROOT`: optional logs folder

## Database Role

- `jobs` stores each processing request
- `job_logs` stores step-by-step logs for each job
- `scheduler_config` stores watched folders and scan rules

## End Result

You get a real backend flow:

- Swagger-based testing
- Postgres persistence
- real folder validation
- real output path creation
- no in-memory simulation

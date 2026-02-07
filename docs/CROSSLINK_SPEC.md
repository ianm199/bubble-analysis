# Crosslink

A multi-language static analysis tool that maps entrypoints and service-to-service calls across codebases, stored in a central SQLite database. Enables IDE navigation and agent reasoning across service boundaries.

## Problem

In a microservice architecture, the call graph is broken at network boundaries. When a developer sees `httpx.post(f"{PAYMENT_SERVICE}/api/charge/{id}")` or `stub.Charge(ctx, req)`, that's a dead end — the IDE has no idea what code handles the other side. Developers manually find the repo, grep for the route, find the handler. Agents are even worse off: they can only reason about one repo at a time and are blind to the distributed topology.

No existing tool solves this with static analysis. OpenAPI requires runtime or heavy annotation. Service meshes operate at the network level. Service catalogs are manually maintained.

## Solution

Crosslink statically extracts two things from every codebase it scans:

1. **Entrypoints** — where services accept incoming requests (HTTP routes, gRPC service methods, message queue consumers)
2. **Service calls** — where services make outgoing requests to other services (HTTP clients, gRPC stubs, queue publishers)

These are stored in a central SQLite database. IDE extensions and agents query the database to resolve cross-service links.

## Design Principles

Carried forward from Bubble:

1. **Canonical identity format** — every entrypoint and service call gets a single unambiguous identifier. This is the backbone of all resolution.
2. **Protocol-based plugins** — structural typing, zero inheritance. Shared logic parameterized by the plugin, not subclassed.
3. **Typed result contracts** — dataclasses decouple extraction from storage from querying. Each layer has a clean interface.
4. **Post-build fixups** — per-file extraction does what it can, then cross-file fixups handle what individual files cannot see.
5. **Cache version bumping** — schema changes invalidate the whole cache. No migration code.
6. **Zero-config by default** — works without configuration. Config exists only for what cannot be auto-detected.
7. **CLI as pure dispatcher** — every command is parse, query, format.

New principles for Crosslink:

8. **Tree-sitter for all languages** — a single parsing strategy across languages. Good enough for framework pattern matching without needing full type resolution.
9. **SQLite as the single source of truth** — no manifest files, no aggregation steps. One database, queryable by everything.
10. **Dual interface from day one** — IDE and agent are first-class consumers, not afterthoughts.

## Architecture

```
                    ┌─────────────────────────────────────┐
                    │          Central SQLite DB           │
                    │  entrypoints + service_calls tables  │
                    └──────────┬──────────┬───────────────┘
                               │          │
                    ┌──────────┘          └──────────┐
                    ▼                                 ▼
             ┌─────────────┐                  ┌─────────────┐
             │ IDE Extension│                  │ Agent Query │
             │ (LSP / Zed) │                  │  Interface  │
             └─────────────┘                  └─────────────┘

                    ▲
                    │ writes
                    │
             ┌─────────────┐
             │  Extractors  │
             │  (per lang)  │
             └──────┬───────┘
                    │ tree-sitter
                    │
     ┌──────────────┼──────────────────┐
     ▼              ▼                  ▼
┌─────────┐  ┌───────────┐     ┌────────────┐
│ Repo A  │  │  Repo B   │     │  Repo C    │
│ Python  │  │  Go       │     │  Node.js   │
│ FastAPI │  │  gRPC     │     │  Express   │
└─────────┘  └───────────┘     └────────────┘
```

### Components

**Extractors** — language-specific modules that use tree-sitter to find entrypoints and service calls. Each extractor is small (100-300 lines) because it only pattern-matches on known framework conventions.

**Central SQLite DB** — the master store. All entrypoints and service calls from all repos live here. One file, queryable by anything.

**IDE Extension** — queries the DB to resolve cross-service links. Provides "go to definition" across service boundaries, CodeLens showing connections, hover information.

**Agent Query Interface** — structured queries an agent can run to understand distributed topology. "What handles POST /api/charge?", "What services does checkout-service call?", "Trace the full chain from frontend to email-service."

**CLI** — the command-line tool for scanning repos, querying the DB, and managing configuration.

## Extraction

### Tree-sitter Strategy

All extraction uses tree-sitter grammars from a single host language (Python). This means:

- One dependency for parsing all languages
- Extractors are Python modules that query tree-sitter ASTs
- No need to install Go, Java, C# toolchains to analyze those languages
- Framework pattern matching works on AST shape, not types — tree-sitter is sufficient

### What Gets Extracted

**Entrypoints** (where a service accepts requests):

| Protocol | Pattern | Example |
|----------|---------|---------|
| HTTP | Route decorator/registration | `@app.get("/users/{id}")` |
| gRPC | Service method implementation | `def Charge(self, request, context)` matching `.proto` |
| Message Queue | Consumer registration | `@celery.task`, `@consumer("topic")` |

**Service Calls** (where a service calls another):

| Protocol | Pattern | Example |
|----------|---------|---------|
| HTTP | Client library calls | `requests.post(url)`, `fetch(url)` |
| gRPC | Stub method calls | `stub.Charge(req)`, `client.GetProduct(ctx, req)` |
| Message Queue | Publisher calls | `queue.publish("topic", msg)` |

### Language × Framework Matrix

Initial targets based on Google Online Boutique + common production stacks:

| Language | Entrypoint Frameworks | Client Libraries |
|----------|----------------------|------------------|
| **Python** | FastAPI, Flask, Django, gRPC (`grpcio`) | `requests`, `httpx`, `aiohttp`, gRPC stubs |
| **JavaScript/TypeScript** | Express, Fastify, NestJS, `@grpc/grpc-js` | `fetch`, `axios`, `node-fetch`, gRPC stubs |
| **Go** | `net/http`, `gorilla/mux`, `gin`, `echo`, `google.golang.org/grpc` | `net/http` client, gRPC stubs |
| **Java** | Spring Boot (`@GetMapping` etc.), `io.grpc` | `RestTemplate`, `WebClient`, `HttpClient`, gRPC stubs |
| **C#** | ASP.NET Core (`[HttpGet]` etc.), `Grpc.AspNetCore` | `HttpClient`, gRPC stubs |

### gRPC: Proto Files as the Bridge

gRPC is uniquely well-suited for cross-service linking because `.proto` files explicitly define the contract. The extraction strategy:

1. Parse `.proto` files to get service definitions (service name, method name, request/response types)
2. In server code, match implemented methods to proto definitions
3. In client code, match stub calls to proto definitions
4. The proto service+method is the join key — no URL pattern matching needed

```protobuf
// hipstershop.proto
service PaymentService {
  rpc Charge(ChargeRequest) returns (ChargeResponse) {}
}
```

Server (Python):
```python
class PaymentServiceServicer(payment_pb2_grpc.PaymentServiceServicer):
    def Charge(self, request, context):  # ← entrypoint
        ...
```

Client (Go):
```go
resp, err := paymentSvc.Charge(ctx, req)  // ← service call
```

Both resolve to `PaymentService.Charge` via the proto definition.

## Canonical Identity

Every entrypoint needs a canonical identity for cross-service resolution. The format depends on the protocol:

### HTTP Entrypoints

```
http:<METHOD> <normalized_path>

Examples:
  http:GET /api/users/{id}
  http:POST /api/charge
  http:GET /products
```

Path parameters are normalized to `{name}` regardless of framework syntax (`<id>`, `:id`, `{id}`).

### gRPC Entrypoints

```
grpc:<package>.<Service>/<Method>

Examples:
  grpc:hipstershop.PaymentService/Charge
  grpc:hipstershop.ProductCatalogService/GetProduct
  grpc:hipstershop.CartService/AddItem
```

Derived directly from proto definitions — no ambiguity.

### Message Queue Entrypoints

```
queue:<system>:<topic_or_queue>

Examples:
  queue:kafka:order-events
  queue:celery:send-email
  queue:rabbitmq:payments
```

### Resolution

Service calls are matched to entrypoints by canonical identity. An HTTP client call to `POST /api/charge` matches any entrypoint with identity `http:POST /api/charge`. A gRPC stub call to `PaymentService.Charge` matches `grpc:hipstershop.PaymentService/Charge`.

Path parameter matching uses pattern comparison: `/api/users/123` matches `/api/users/{id}`.

## SQLite Schema

```sql
CREATE TABLE services (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    repo_url    TEXT,
    local_path  TEXT,
    language    TEXT,
    frameworks  TEXT,  -- JSON array: ["fastapi", "grpc"]
    last_scanned TIMESTAMP,
    scan_version TEXT
);

CREATE TABLE entrypoints (
    id              INTEGER PRIMARY KEY,
    service_id      INTEGER NOT NULL REFERENCES services(id),
    canonical_id    TEXT NOT NULL,  -- "http:POST /api/charge" or "grpc:Payment/Charge"
    protocol        TEXT NOT NULL,  -- "http", "grpc", "queue"

    -- HTTP-specific
    http_method     TEXT,
    http_path       TEXT,

    -- gRPC-specific
    grpc_service    TEXT,
    grpc_method     TEXT,
    proto_file      TEXT,

    -- Queue-specific
    queue_system    TEXT,
    queue_topic     TEXT,

    -- Handler location
    handler_file    TEXT NOT NULL,
    handler_function TEXT NOT NULL,
    handler_line    INTEGER,

    -- Metadata
    framework       TEXT,  -- "fastapi", "gin", "grpc", etc.
    last_updated    TIMESTAMP
);

CREATE TABLE service_calls (
    id              INTEGER PRIMARY KEY,
    service_id      INTEGER NOT NULL REFERENCES services(id),
    target_canonical_id TEXT,  -- resolved canonical ID (nullable if unresolved)

    protocol        TEXT NOT NULL,  -- "http", "grpc", "queue"

    -- HTTP-specific
    http_method     TEXT,
    http_url        TEXT,  -- raw URL expression as found in source

    -- gRPC-specific
    grpc_service    TEXT,
    grpc_method     TEXT,

    -- Queue-specific
    queue_system    TEXT,
    queue_topic     TEXT,

    -- Call location
    source_file     TEXT NOT NULL,
    source_function TEXT NOT NULL,
    source_line     INTEGER,

    -- Metadata
    framework       TEXT,  -- "requests", "httpx", "grpc-stub", etc.
    last_updated    TIMESTAMP
);

-- Indexes for fast resolution
CREATE INDEX idx_entrypoints_canonical ON entrypoints(canonical_id);
CREATE INDEX idx_entrypoints_service ON entrypoints(service_id);
CREATE INDEX idx_service_calls_target ON service_calls(target_canonical_id);
CREATE INDEX idx_service_calls_service ON service_calls(service_id);

-- Materialized cross-service links (populated after scan)
CREATE TABLE resolved_links (
    id              INTEGER PRIMARY KEY,
    call_id         INTEGER NOT NULL REFERENCES service_calls(id),
    entrypoint_id   INTEGER NOT NULL REFERENCES entrypoints(id),
    confidence      TEXT NOT NULL,  -- "exact", "pattern", "heuristic"
    resolved_at     TIMESTAMP
);

CREATE INDEX idx_resolved_source ON resolved_links(call_id);
CREATE INDEX idx_resolved_target ON resolved_links(entrypoint_id);
```

### Resolution Confidence

| Level | Meaning | Example |
|-------|---------|---------|
| `exact` | Canonical IDs match exactly | gRPC stub call → gRPC service method via proto |
| `pattern` | URL pattern match with path params | `POST /users/123` → `POST /users/{id}` |
| `heuristic` | URL partially extracted, best-effort match | Dynamic URL construction with some constants |

## Plugin System

### Extractor Protocol

```python
from dataclasses import dataclass
from typing import Protocol

@dataclass
class ExtractedEntrypoint:
    canonical_id: str
    protocol: str
    handler_file: str
    handler_function: str
    handler_line: int
    framework: str
    metadata: dict[str, str]

@dataclass
class ExtractedServiceCall:
    protocol: str
    target_canonical_id: str | None
    source_file: str
    source_function: str
    source_line: int
    framework: str
    raw_target: str
    metadata: dict[str, str]

@dataclass
class ExtractionResult:
    entrypoints: list[ExtractedEntrypoint]
    service_calls: list[ExtractedServiceCall]

class Extractor(Protocol):
    """
    An extractor detects entrypoints and service calls for a specific
    language + framework combination.
    """
    name: str
    language: str
    framework: str

    def detect(self, file_path: str, tree: Tree, source: bytes) -> ExtractionResult:
        """
        Given a parsed tree-sitter AST and the raw source bytes,
        return all entrypoints and service calls found in this file.
        """
        ...

    def applicable(self, file_path: str) -> bool:
        """
        Quick check: should this extractor run on this file?
        Based on extension, path patterns, etc.
        """
        ...
```

### Built-in Extractors

Organized by language, each is a self-contained module:

```
crosslink/
├── extractors/
│   ├── python/
│   │   ├── fastapi.py      # @app.get, @router.post, APIRouter
│   │   ├── flask.py        # @app.route, Blueprint
│   │   ├── django.py       # urlpatterns, path(), ViewSet
│   │   ├── grpc_server.py  # servicer implementations
│   │   ├── requests.py     # requests.get/post/put/delete
│   │   ├── httpx.py        # httpx client calls
│   │   ├── grpc_client.py  # stub calls
│   │   └── celery.py       # @task, .delay(), .apply_async()
│   │
│   ├── javascript/
│   │   ├── express.py      # app.get, router.post
│   │   ├── fastify.py      # fastify.get
│   │   ├── nestjs.py       # @Get, @Post decorators
│   │   ├── grpc_server.py  # @grpc/grpc-js service impl
│   │   ├── fetch.py        # fetch() calls
│   │   ├── axios.py        # axios.get/post
│   │   └── grpc_client.py  # grpc stub calls
│   │
│   ├── go/
│   │   ├── net_http.py     # http.HandleFunc, mux.HandleFunc
│   │   ├── gin.py          # r.GET, r.POST
│   │   ├── echo.py         # e.GET, e.POST
│   │   ├── grpc_server.py  # RegisterXServiceServer
│   │   ├── http_client.py  # http.Get, http.Post, http.NewRequest
│   │   └── grpc_client.py  # stub calls
│   │
│   ├── java/
│   │   ├── spring.py       # @GetMapping, @RestController
│   │   ├── grpc_server.py  # extends *ImplBase
│   │   ├── http_client.py  # RestTemplate, WebClient, HttpClient
│   │   └── grpc_client.py  # stub calls
│   │
│   ├── csharp/
│   │   ├── aspnet.py       # [HttpGet], [ApiController]
│   │   ├── grpc_server.py  # inherits *.ServiceBase
│   │   ├── http_client.py  # HttpClient
│   │   └── grpc_client.py  # stub calls
│   │
│   └── proto/
│       └── parser.py       # .proto file parser → service definitions
│
├── core/
│   ├── models.py           # ExtractedEntrypoint, ExtractedServiceCall, etc.
│   ├── db.py               # SQLite operations
│   ├── resolver.py         # Match service_calls to entrypoints
│   ├── registry.py         # Extractor discovery and loading
│   └── scanner.py          # Orchestrates scanning a repo
│
├── interfaces/
│   ├── lsp.py              # Language Server Protocol for IDE integration
│   ├── agent.py            # Structured query interface for agents
│   └── mcp.py              # Model Context Protocol server
│
├── cli.py                  # CLI commands
└── config.py               # Configuration
```

### Custom Extractors

Users can write custom extractors for internal frameworks. Placed in a `.crosslink/extractors/` directory in the repo or in `~/.crosslink/extractors/` globally:

```python
# .crosslink/extractors/internal_rpc.py
from crosslink.extractors.base import Extractor, ExtractionResult, ExtractedEntrypoint

class InternalRpcExtractor:
    name = "internal-rpc"
    language = "python"
    framework = "internal-rpc"

    def applicable(self, file_path: str) -> bool:
        return file_path.endswith(".py")

    def detect(self, file_path, tree, source) -> ExtractionResult:
        entrypoints = []
        # tree-sitter query for @rpc_handler("method_name") decorators
        query = LANGUAGE.query("""
            (decorated_definition
              (decorator
                (call
                  function: (identifier) @dec_name
                  arguments: (argument_list (string) @method_name)))
              definition: (function_definition name: (identifier) @func_name))
        """)
        for match in query.matches(tree.root_node):
            # ... extract and append
        return ExtractionResult(entrypoints=entrypoints, service_calls=[])
```

This follows the Bubble pattern: the shared logic (scanning, DB, resolution, IDE integration) does the heavy lifting. Custom extractors only need to detect patterns and return structured data.

## Agent Interface

### MCP Server

The primary agent interface is an MCP (Model Context Protocol) server. This lets any MCP-compatible agent query the topology naturally:

**Tools exposed:**

```
resolve_endpoint(method, path) → handler location + service
  "What handles POST /api/charge?"

list_service_entrypoints(service) → all entrypoints
  "What endpoints does payment-service expose?"

list_service_dependencies(service) → outgoing calls + resolved targets
  "What other services does checkout-service call?"

trace_chain(method, path) → full call chain across services
  "Trace the full path from POST /checkout to the email service"

find_callers(service, entrypoint) → all service_calls that resolve to this entrypoint
  "Who calls PaymentService.Charge?"

topology() → service dependency graph
  "Show me the full service graph"
```

**Context resources exposed:**

```
service://{name}/entrypoints  → all entrypoints for a service
service://{name}/dependencies → all outbound calls for a service
topology://graph              → full service dependency graph as adjacency list
```

### Why MCP

MCP is the right interface for agents because:

- It is the emerging standard for tool-use by LLMs
- It works with Claude, and other MCP-compatible agents
- The tool/resource model maps naturally to the queries agents need
- It runs as a local server — no authentication complexity
- Agents get structured data, not CLI text output

### Agent Workflows

**Incident debugging:**
Agent receives "500 error on POST /checkout". It can:
1. `resolve_endpoint("POST", "/checkout")` → checkout-service, `handlers/checkout.go:42`
2. `list_service_dependencies("checkout-service")` → calls payment, shipping, email, cart
3. `resolve_endpoint("POST", "/api/charge")` → payment-service, `charge.py:18`
4. Now the agent has the full chain and can read the relevant handler code in each repo

**Impact analysis:**
Agent is asked "what breaks if we change the PaymentService.Charge response?"
1. `find_callers("payment-service", "grpc:hipstershop.PaymentService/Charge")` → checkout-service calls it from `checkout.go:87`
2. `find_callers("checkout-service", "http:POST /checkout")` → frontend calls it
3. Agent knows the blast radius: frontend → checkout → payment

**Onboarding:**
Agent is asked "explain how the checkout flow works"
1. `trace_chain("POST", "/cart/checkout")` → gets the full service chain
2. Agent can now explain the flow with specific file/line references across repos

## IDE Interface

### LSP Integration

Crosslink runs as an LSP server (or extends an existing one) to provide:

**Go to Definition (cross-service):**
When the cursor is on a service call like `requests.post(f"{PAYMENT}/api/charge/{id}")`, "go to definition" opens the handler file in the target service's repo (if locally available) or shows the location.

**Hover Information:**
Hovering on a service call shows:
```
→ payment-service
  POST /api/charge/{id}
  Handler: routes/charges.py::create_charge (line 42)
  Protocol: HTTP
```

**CodeLens:**
Above entrypoint handlers, show inbound callers:
```
Called by: checkout-service (checkout.go:87), frontend (api.ts:23)
@app.post("/api/charge/{id}")
def create_charge(id: str, req: ChargeRequest):
```

**References (cross-service):**
"Find all references" on an entrypoint handler includes cross-service callers.

### Zed Extension

Zed is the primary IDE target given current usage. The extension:
- Registers as an LSP client for all supported languages
- Queries the SQLite DB directly (or via the LSP server)
- Provides go-to-definition, hover, and CodeLens

### VS Code Extension

Secondary target. Same capabilities, packaged as a VS Code extension.

## CLI

```bash
# Scanning
crosslink scan <repo_path>              # Scan a repo and update the DB
crosslink scan <repo_path> --service-name payment-service
crosslink scan --all                    # Re-scan all registered repos

# Querying
crosslink resolve POST /api/charge      # What handles this endpoint?
crosslink entrypoints <service>         # List all entrypoints for a service
crosslink dependencies <service>        # What does this service call?
crosslink callers <service> <endpoint>  # Who calls this endpoint?
crosslink trace POST /checkout          # Full cross-service chain
crosslink topology                      # Service dependency graph

# Management
crosslink services                      # List registered services
crosslink add <repo_path> --name svc    # Register a repo
crosslink remove <service>              # Unregister a service
crosslink status                        # DB stats, stale services, etc.

# Agent
crosslink mcp                           # Start MCP server
crosslink agent-context <service>       # Dump structured context for an agent
```

## Configuration

### Global Config (`~/.crosslink/config.yaml`)

```yaml
db_path: ~/.crosslink/crosslink.sqlite

custom_extractors:
  - ~/.crosslink/extractors/

services:
  payment-service:
    path: ~/repos/payment-service
    repo: github.com/org/payment-service
  checkout-service:
    path: ~/repos/checkout-service
    repo: github.com/org/checkout-service

url_mappings:
  PAYMENT_SERVICE: payment-service
  USER_SERVICE: user-service

scan:
  exclude:
    - "**/node_modules/**"
    - "**/venv/**"
    - "**/.venv/**"
    - "**/vendor/**"
    - "**/__pycache__/**"
```

### Per-Repo Config (`.crosslink/config.yaml`)

```yaml
service_name: payment-service

custom_extractors:
  - .crosslink/extractors/

entrypoint_patterns:
  - "routes/**"
  - "handlers/**"

ignore:
  - "tests/**"
  - "scripts/**"
```

### URL Mapping

The hardest part of HTTP resolution is that base URLs are typically environment variables or constants. The `url_mappings` config maps those to services:

```yaml
url_mappings:
  PAYMENT_SERVICE: payment-service
  PAYMENT_URL: payment-service
  os.environ["PAYMENT_HOST"]: payment-service
```

This is inherently imperfect and that's fine. gRPC resolution via proto files is exact. HTTP resolution is best-effort with config hints. Even 80% coverage is vastly better than 0%.

## Dogfooding Plan

### Phase 1: Google Online Boutique

The primary development target. 11 services, 5 languages, gRPC throughout.

**Why it's ideal:**
- Public, well-documented, stable
- Multi-language: Go (4), Python (3), Node.js (2), C# (1), Java (1)
- gRPC for inter-service communication — proto files provide exact resolution
- Clear service boundaries and well-defined call patterns
- The checkout flow exercises the full chain: frontend → checkout → {cart, product catalog, shipping, currency, payment, email}

**Milestone:** `crosslink scan` all 11 services, `crosslink topology` produces the correct service graph, `crosslink trace POST /cart/checkout` produces the full chain from frontend through checkout to all downstream services.

### Phase 2: Bubble + Crosslink (Self-Hosting)

Use Crosslink to analyze itself alongside Bubble. Two Python repos, shared patterns, some cross-repo utility potential.

### Phase 3: Real Microservices

The actual target use case. Partner with a team (or use your own projects) that has 3+ services calling each other in production. This is where HTTP resolution, URL mapping, and the agent debugging workflow get tested for real.

## Implementation Roadmap

### v0.1 — Foundation + gRPC (Dogfood: Online Boutique)

**Goal:** Scan Online Boutique, produce correct topology.

- [ ] Core models and SQLite schema
- [ ] Proto file parser (entrypoint definitions + service contracts)
- [ ] Tree-sitter setup for Python, Go, Node.js, Java, C#
- [ ] gRPC server extractors (all 5 languages)
- [ ] gRPC client extractors (all 5 languages)
- [ ] Go HTTP entrypoint extractor (`gorilla/mux`, `net/http`)
- [ ] Resolver: match service calls to entrypoints
- [ ] CLI: `scan`, `topology`, `resolve`, `entrypoints`, `dependencies`
- [ ] Scan all 11 Online Boutique services successfully

### v0.2 — HTTP Extraction + IDE

**Goal:** HTTP routes and client calls. Basic IDE integration.

- [ ] Python HTTP entrypoint extractors (FastAPI, Flask, Django)
- [ ] JavaScript HTTP entrypoint extractors (Express, Fastify)
- [ ] Python HTTP client extractors (requests, httpx)
- [ ] JavaScript HTTP client extractors (fetch, axios)
- [ ] Go HTTP client extractor
- [ ] URL pattern matching and normalization
- [ ] URL mapping configuration
- [ ] LSP server with go-to-definition and hover
- [ ] Zed extension (primary)

### v0.3 — Agent Interface + Custom Extractors

**Goal:** Agents can query the topology. Users can extend for internal frameworks.

- [ ] MCP server with all tool and resource endpoints
- [ ] Agent context dump command
- [ ] Custom extractor loading from `.crosslink/extractors/`
- [ ] Plugin registry with auto-discovery
- [ ] `crosslink trace` for full chain visualization
- [ ] VS Code extension

### v0.4 — Message Queues + Polish

**Goal:** Async communication patterns. Production readiness.

- [ ] Celery task/consumer extractors
- [ ] Kafka producer/consumer extractors
- [ ] RabbitMQ publisher/consumer extractors
- [ ] CI integration (scan on push, keep DB fresh)
- [ ] Incremental scanning (only re-extract changed files)
- [ ] CodeLens showing inbound callers on entrypoints

## Open Questions

1. **DB location for teams.** SQLite works great locally. For a team, the DB needs to be shared. Options: committed to a repo, stored on a shared drive, generated in CI and pushed to S3, or a thin server wrapping SQLite. Start local, solve sharing later.

2. **Monorepo support.** Some orgs put all services in one repo. The scan should detect service boundaries (separate `go.mod`, `pyproject.toml`, `package.json`) and treat each as a distinct service.

3. **Dynamic URL construction.** `f"{base_url}/api/{version}/users"` is common and hard to parse statically. The URL mapping config helps, but there's a long tail. Accept imperfection — gRPC is exact, HTTP is best-effort.

4. **Proto file location.** Proto files might live in the service repo, a shared proto repo, or be generated. Need a way to point Crosslink at proto sources.

5. **Language for the tool itself.** Python is natural given Bubble experience and tree-sitter-python bindings. Rust would be faster for large-scale scanning. Python first, consider Rust rewrite for the scanner if performance matters.

## Future Exploration: Static Contract Verification

Crosslink's topology data opens a thread worth pulling on: using the cross-service link graph as a form of static integration testing.

The idea is not to replace running services in docker-compose — that's simpler and more reliable for behavioral testing. The idea is that Crosslink already knows the interface between services, and that knowledge can catch a class of breakage without running anything.

### What This Could Look Like

**Broken link detection:** Service B renames `POST /api/charge` to `POST /api/payments/charge`. Crosslink re-scans and flags that Service A still calls the old path. A `crosslink verify` command that checks all resolved links still resolve, run in CI on every push.

**Contract drift for gRPC:** Proto files define the contract explicitly. Crosslink can verify that server implementations still match the proto (all methods implemented, signatures compatible) and that client stubs are calling methods that still exist. This is particularly strong because proto resolution is exact.

**Coverage mapping:** "These two services are linked but no integration test in CI covers that connection." Not generating tests, but identifying where you're exposed. Crosslink knows the edges in the service graph; a CI integration could track which edges are exercised by existing integration tests and report gaps.

**Generated contract tests:** For HTTP services, extracting request/response shapes from type annotations (Pydantic models, TypeScript interfaces, Go structs) and generating Pact-style contract stubs. The topology tells you which contracts to generate; the type extraction fills in the shape.

### Why This Is a Starting Point

Each of these is a different depth of analysis built on the same foundation. Broken link detection is trivial once you have the topology — it's just re-running resolution and checking for failures. Contract drift for gRPC is moderately complex. Full contract generation from type annotations is a significant extension.

The important thing is that none of these require changes to the core architecture. The SQLite schema, extractors, and resolution logic are the same. Verification is a new query layer on top of the existing data, not a new extraction pass.

# Flow Zed Extension: Technical Spec

## Overview

Build a Zed editor extension that surfaces Flow's exception analysis directly in the editor via hover, diagnostics, and workspace commands. The system has two parts:

1. **Python LSP server** (`bubble/lsp.py`) — pygls 2.0 server wrapping the existing query engine
2. **Zed extension** (separate repo, Rust → WASM) — ~50 lines of boilerplate that tells Zed to spawn the Python server

Zed handles all LSP message routing and UI rendering. The extension just says "run this process." All the real logic lives in the Python server.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                       Zed                           │
│                                                     │
│  ┌───────────────────────────────────────────────┐  │
│  │          flow-zed extension (WASM)            │  │
│  │  - Returns Command to spawn bubble-lsp        │  │
│  │  - Passes through LspSettings                 │  │
│  │  - ~50 lines of Rust                          │  │
│  └───────────────────┬───────────────────────────┘  │
│                      │                              │
│              stdio (LSP protocol)                   │
│                      │                              │
│  Zed renders: hover tooltips, diagnostics,          │
│  squiggly lines, code actions — all natively        │
└──────────────────────┼──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              bubble-lsp (Python, pygls 2.0)         │
│                                                     │
│  ┌─────────────┐  ┌────────────┐  ┌─────────────┐  │
│  │ Hover       │  │ Diagnostics│  │ Commands     │  │
│  │ handler     │  │ publisher  │  │ (future)     │  │
│  └──────┬──────┘  └─────┬──────┘  └─────────────┘  │
│         │               │                           │
│         ▼               ▼                           │
│  ┌─────────────────────────────────────────────┐    │
│  │           Cached ProgramModel               │    │
│  │  Built on startup, refreshed on file save   │    │
│  └──────────────────┬──────────────────────────┘    │
│                     │                               │
│                     ▼                               │
│  ┌─────────────────────────────────────────────┐    │
│  │         Existing Flow Core Library          │    │
│  │  extractor.py · propagation.py · queries.py │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

## Prior Art: Zed Extensions to Study

Before building, read the source of 10-20 existing Zed extensions to understand real-world patterns. Focus on extensions that wrap external LSP servers, especially Python-based ones.

### Must-Read (Python LSP wrappers)

These are the closest analogs to what we're building:

- [ ] **python-lsp-zed-extension** (rgbkrk) — wraps `pylsp`, expects pre-installed binary. ~60 lines of Rust. The template for our extension.
- [ ] **pyrefly** (zed-extensions) — Meta's Python type checker. Shows `LspSettings` binary path override pattern.
- [ ] **ruff** (zed-extensions) — Ruff linter integration. Shows how a Python analysis tool integrates.
- [ ] **pyright** (zed-extensions) — Pyright type checker. Node-based LSP, but similar pattern.
- [ ] **basedpyright** (zed-extensions) — Fork of pyright with extra features.

### Should-Read (LSP patterns and installation strategies)

- [ ] **dockerfile** (zed-extensions) — NPM-based server installation with `npm_install_package()`.
- [ ] **toml** (zed-extensions) — Taplo TOML LSP, downloads binary from GitHub releases.
- [ ] **yaml** (zed-extensions) — YAML language server, good lifecycle example.
- [ ] **json** (zed-extensions) — JSON language server, shows workspace configuration passthrough.
- [ ] **terraform** (zed-extensions) — Downloads terraform-ls binary, shows platform detection.

### Nice-to-Read (advanced patterns)

- [ ] **vtsls** (zed-extensions) — TypeScript LSP, complex configuration passthrough.
- [ ] **lua** (zed-extensions) — Lua language server, shows initialization options.
- [ ] **elixir** (zed-extensions) — Elixir LSP, shows workspace configuration.
- [ ] **ruby-lsp** (zed-extensions) — Ruby LSP, shows process management patterns.
- [ ] **emmet** (zed-extensions) — Shows code label customization.
- [ ] **tailwindcss** (zed-extensions) — Shows how to handle server that needs specific working directory.

### What to Extract from Each

For each extension, document:
1. Total lines of Rust code
2. How it finds/installs the language server binary
3. What `language_server_command()` returns
4. Whether it uses `initialization_options` or `workspace_configuration`
5. Any error handling patterns
6. Any platform-specific logic

## Component 1: Python LSP Server (`bubble/lsp.py`)

### Dependencies

Add to `pyproject.toml`:
```toml
[project.optional-dependencies]
lsp = ["pygls>=2.0,<3.0"]
```

Add script entry point:
```toml
[project.scripts]
bubble = "bubble.cli:app"
bubble-lsp = "bubble.lsp:main"
```

### pygls 2.0 API Surface

Key imports (v2 paths, not v1):
```python
from pygls.lsp.server import LanguageServer
from pygls.workspace import TextDocument
from lsprotocol import types
```

Key v2 changes from v1:
- `LanguageServer` import moved to `pygls.lsp.server`
- `Document` renamed to `TextDocument`
- `workspace.get_document()` renamed to `workspace.get_text_document()`
- `server.publish_diagnostics()` renamed to `server.text_document_publish_diagnostics()`
- Custom notifications via `server.protocol.notify()` not `server.send_notification()`

### Phase 0: Skeleton Server -- DONE

Static hover message on every Python file. Proved the pipeline works end-to-end.

### Phase 1: Context-Sensitive Hover -- DONE

Three-way dispatch based on cursor position using the existing program model:
- `def` lines → full exception flow via `compute_exception_flow`
- Function calls → callee exceptions via `propagated_raises[callee_key]` lookup
- Elsewhere → no hover

Uses `CallSite` data from the model (file + line) to match call sites without re-parsing. Reraise patterns filtered from all output.

### Phase 2: Route Diagnostics -- DONE

Warning-level squiggly lines on route decorators (`@router.get(...)`, `@app.route(...)`) where uncaught exceptions can escape. Published on `didOpen` and `didSave` via `textDocument/publishDiagnostics`.

Suppression via comments:
- `# bubble: ignore` — suppress all warnings on a route
- `# bubble: ignore[ValueError, KeyError]` — suppress specific types

### Phase 3: Hover on Except Blocks -- TODO

Same position-mapping problem, but for `ExceptHandler` nodes instead of `Call` nodes.

### Model Lifecycle

```
File opened (didOpen)
    → Build ProgramModel if not cached
    → Compute propagation (cached per model instance)
    → Publish diagnostics for the file

File saved (didSave)
    → Invalidate model (full rebuild on next query)
    → Republish diagnostics

Hover request
    → Reuse cached model and propagation
    → Dict lookup for results
```

### Workspace Root Discovery

The LSP `initialize` request includes `rootUri` / `workspaceFolders`. Use this as the directory passed to `extract_from_directory()`. Fall back to scanning for `.flow/` config directory.

## Component 2: Zed Extension (`flow-zed/`)

### Repository Structure

```
flow-zed/
├── extension.toml
├── Cargo.toml
├── LICENSE           (required for Zed extension registry)
├── README.md
└── src/
    └── lib.rs
```

### extension.toml

```toml
id = "flow-exception-analysis"
name = "Flow Exception Analysis"
version = "0.0.1"
schema_version = 1
authors = ["Ian McLaughlin <ianm199@github.com>"]
description = "See exception flow through your Python codebase — hover to see what can raise, what's caught, what escapes"
repository = "https://github.com/ianm199/flow-zed"

[language_servers.bubble-lsp]
name = "Flow Exception Analysis"
languages = ["Python"]
```

### Cargo.toml

```toml
[package]
name = "flow-zed"
version = "0.0.1"
edition = "2021"

[lib]
crate-type = ["cdylib"]

[dependencies]
zed_extension_api = "0.7.0"
```

### src/lib.rs

```rust
use zed_extension_api::{self as zed, settings::LspSettings, Result};

struct FlowExtension;

impl zed::Extension for FlowExtension {
    fn new() -> Self {
        Self
    }

    fn language_server_command(
        &mut self,
        _id: &zed::LanguageServerId,
        worktree: &zed::Worktree,
    ) -> Result<zed::Command> {
        if let Ok(lsp_settings) = LspSettings::for_worktree("bubble-lsp", worktree) {
            if let Some(binary) = lsp_settings.binary {
                if let Some(path) = binary.path {
                    let args = binary.arguments.unwrap_or_default();
                    return Ok(zed::Command {
                        command: path,
                        args,
                        env: worktree.shell_env(),
                    });
                }
            }
        }

        let python = worktree
            .which("python3")
            .or_else(|| worktree.which("python"))
            .ok_or_else(|| "Python not found in PATH".to_string())?;

        Ok(zed::Command {
            command: python,
            args: vec!["-m".to_string(), "bubble.lsp".to_string()],
            env: worktree.shell_env(),
        })
    }

    fn language_server_initialization_options(
        &mut self,
        server_id: &zed::LanguageServerId,
        worktree: &zed::Worktree,
    ) -> Result<Option<zed::serde_json::Value>> {
        let settings = LspSettings::for_worktree(server_id.as_ref(), worktree)
            .ok()
            .and_then(|s| s.initialization_options.clone())
            .unwrap_or_default();
        Ok(Some(settings))
    }

    fn language_server_workspace_configuration(
        &mut self,
        server_id: &zed::LanguageServerId,
        worktree: &zed::Worktree,
    ) -> Result<Option<zed::serde_json::Value>> {
        let settings = LspSettings::for_worktree(server_id.as_ref(), worktree)
            .ok()
            .and_then(|s| s.settings.clone())
            .unwrap_or_default();
        Ok(Some(settings))
    }
}

zed::register_extension!(FlowExtension);
```

### User Configuration (Zed settings.json)

Users configure the server via Zed's LSP settings:

```json
{
  "lsp": {
    "bubble-lsp": {
      "binary": {
        "path": "/path/to/custom/python",
        "arguments": ["-m", "bubble.lsp"]
      },
      "settings": {
        "confidenceThreshold": "medium",
        "showDiagnostics": false,
        "stubPaths": [".flow/stubs"],
        "excludePatterns": ["**/tests/**", "**/venv/**"]
      }
    }
  }
}
```

### Build and Test

Prerequisites:
```bash
rustup target add wasm32-wasip1
```

Development workflow:
1. Open `flow-zed/` directory in Zed
2. Command palette → "zed: install dev extension"
3. Zed compiles Rust → WASM and loads it
4. Open a Python project, hover over code
5. Debug: command palette → "zed: open log"
6. After changes: click "Rebuild" button

### Zed Capabilities

What Zed supports from LSP (we can use all of these):
- **textDocument/hover** — tooltip on hover
- **textDocument/publishDiagnostics** — squiggly underlines with messages
- **textDocument/codeAction** — quick fixes (lightbulb menu)
- **textDocument/definition** — go-to-definition
- **workspace/symbol** — workspace-wide symbol search

What Zed does NOT support:
- **Code Lens** — inline annotations above functions (not available)
- **Inline hints** may have limited support

## Phased Rollout

### Phase 0: Prove the Pipeline — DONE

- [x] Add `pygls>=2.0` as optional dependency
- [x] Create `bubble/lsp.py` with skeleton server
- [x] Add `bubble-lsp` script entry point
- [x] Create Zed extension in `editors/zed/`
- [x] Install dev extension in Zed, verify hover works

### Phase 1: Context-Sensitive Hover — DONE

- [x] Hover on `def` line: full exception flow via `compute_exception_flow`
- [x] Hover on function call: callee exceptions via `propagated_raises` lookup
- [x] Hover elsewhere: no popup (returns `None`)
- [x] Reraise pattern filtering (`e`, `ex`, `err`, `exc`, `error`, `exception`, `Unknown`)
- [x] Unscoped cached propagation (first hover builds, all subsequent are dict lookups)
- [x] Model built lazily on first query, invalidated on `didSave`

### Phase 2: Except Block Hover + Model Refresh

- [ ] Add except-block position detection
- [ ] Show caught vs. escaping exceptions on except hover
- [ ] Reuse existing SQLite file cache for extraction persistence

### Phase 3: Diagnostics

- [ ] Publish diagnostics for route handlers with uncaught exceptions
- [ ] Warning severity only, opt-in via settings
- [ ] Include confidence level in diagnostic message
- [ ] Suppression via `# flow: ignore` comments

### Phase 4: Polish

- [ ] Progress reporting during initial indexing (`window/workDoneProgress`)
- [ ] Workspace configuration passthrough from Zed settings
- [ ] Performance profiling for large codebases
- [ ] Publish extension to Zed extension registry

## Open Questions

1. **Should `bubble-lsp` be a separate package or stay in `bubble-analysis`?** Leaning toward same package with optional `[lsp]` dependency group. Keeps everything in one repo, one version.

2. **How to handle projects where `bubble-analysis` isn't installed in the active Python environment?** The extension could check for the package and show a clear error. Or we could eventually ship a standalone binary via PyInstaller.

3. **Should hover show info for ALL positions or only function calls?** Resolved: hover on `def` lines shows full exception flow, hover on calls shows callee exceptions, everything else returns nothing. Except blocks are Phase 2.

4. **Debounce strategy for `didChange` vs `didSave`?** Start with `didSave` only (simpler, matches existing cache invalidation). Move to debounced `didChange` if the latency is acceptable.

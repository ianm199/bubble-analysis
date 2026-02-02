# Bubble Tool Improvement Cycle

## Overview

This document tracks the dogfood → improve → validate cycle for the bubble tool.

**Goal**: Find real bugs in open source projects using the tool (not manual analysis), then write a compelling blog post about it.

**Current state**: We found 16+ bugs manually, but the tool missed most of them due to framework coverage gaps.

---

## Cycle 1: Flask-RESTful Support ✅ COMPLETED

### Phase 1: Implementation

**Issue**: `docs/issues/flask-restful-support.md`

| Task | Status | Notes |
|------|--------|-------|
| Create `FlaskRESTfulVisitor` class | ✅ Done | Detects Resource classes + add_resource() calls |
| Integrate with existing Flask detector | ✅ Done | Both visitors run, results merged |
| Create test fixtures | ✅ Done | `tests/fixtures/flask_restful_app/` |
| Write unit tests | ✅ Done | `tests/test_flask_restful.py` - 5 tests |

**Actual effort**: ~2 hours

### Phase 2: Validation

| Task | Status | Notes |
|------|--------|-------|
| Run `bubble flask entrypoints` on Redash | ✅ Done | **191 endpoints** detected (vs 9 before) |
| Run `bubble flask audit` on Redash | ✅ Done | All explicit raises covered |
| Verify no regression on httpbin | ✅ Done | 147/148 tests pass (1 flaky pre-existing) |

### Key Learning: Scope Boundary

The tool detects **explicit `raise` statements** only. Implicit exceptions from operations like `dict["key"]` are out of scope - type checkers handle those.

The 8 KeyError bugs in Redash are from `request.json["field"]` patterns (implicit), not explicit raises. This is the correct scope boundary.

### Phase 3: Documentation

| Task | Status | Notes |
|------|--------|-------|
| Update `confirmed-bugs-found.md` | ⬜ TODO | Note scope boundary |
| Update DOGFOODING.md results | ⬜ TODO | Add Redash to completed section |

---

## Cycle 2: Datasette/ASGI Support (Optional)

### Phase 1: Implementation

**Research**: See scratchpad `asgi-datasette-patterns.md`

| Task | Status | Notes |
|------|--------|-------|
| Create `bubble/integrations/datasette/` | ⬜ TODO | New integration directory |
| Implement `register_routes()` hook detection | ⬜ TODO | Parse function body for route tuples |
| Create test fixtures | ⬜ TODO | `tests/fixtures/datasette_app/` |
| Write unit tests | ⬜ TODO | `tests/test_datasette.py` |

**Estimated effort**: 8-12 hours

### Phase 2: Validation

| Task | Status | Notes |
|------|--------|-------|
| Run `bubble datasette audit` on Datasette | ⬜ TODO | Should find the 5 JSONDecodeError bugs |
| Live-test bugs on datasette.io | ⬜ TODO | Confirm 500s still happen |

---

## Cycle 3: DRF Improvements

### Known Issues

| Issue | Status | Notes |
|-------|--------|-------|
| Route names show as "?" | ⬜ TODO | Label Studio audit showed "? ?" for routes |
| Local catches not detected | ⬜ TODO | Tool flagged raises inside try blocks |

### Validation

| Task | Status | Notes |
|------|--------|-------|
| Re-audit Label Studio | ⬜ TODO | After fixes, routes should show properly |
| Verify 3 bugs found by tool | ⬜ TODO | DataManagerException + Storage sync |

---

## Success Criteria

Before writing the blog post, we need:

1. **Flask-RESTful working**
   - [ ] `bubble flask audit` finds the 8 Redash bugs automatically
   - [ ] Tests cover all Flask-RESTful patterns

2. **At least one "live demo" bug**
   - [ ] A bug we can trigger with curl against a public endpoint
   - [ ] httpbin digest-auth or Datasette JSON parsing work for this

3. **Clean audit output**
   - [ ] No "? ?" route names
   - [ ] False positive rate < 30%

4. **Blog-ready documentation**
   - [ ] `confirmed-bugs-found.md` shows bugs found BY THE TOOL
   - [ ] Can show tool output, not just manual findings

---

## Quick Reference: What We Have

### Research (in scratchpad)
- `flask-restful-patterns.md` - How to detect Flask-RESTful
- `asgi-datasette-patterns.md` - How to detect Datasette routes
- `redash-bugs.md` - 8 confirmed bugs
- `datasette-bugs.md` - 5 confirmed bugs
- `labelstudio-deep-dive.md` - 3 confirmed bugs with curl examples

### Implementation Plans
- `docs/issues/flask-restful-support.md` - Detailed implementation plan
- `docs/issues/confirmed-bugs-found.md` - All bugs we've found

### Test Repos (in /tmp)
- `/tmp/redash-audit` - Redash clone for testing
- `/tmp/datasette-audit` - Datasette clone for testing
- `/tmp/label-studio-audit` - Label Studio clone for testing

---

## Priority Order

1. **Flask-RESTful** (highest impact, medium effort)
   - Unlocks Redash (26k stars, 8 bugs)
   - Common pattern in Flask apps

2. **DRF improvements** (medium impact, low effort)
   - Route name detection is a small fix
   - Unlocks clean Label Studio output

3. **Datasette/ASGI** (lower priority, higher effort)
   - Only helps Datasette-like apps
   - Can do this later or skip for blog

---

## Next Steps

```bash
# Start with Flask-RESTful implementation
cd /Users/ianmclaughlin/PycharmProjects/flow2/flow

# 1. Create test fixtures first (TDD)
mkdir -p tests/fixtures/flask_restful_app
# Create app.py with Flask-RESTful patterns

# 2. Write failing tests
# tests/test_flask_restful.py

# 3. Implement FlaskRESTfulVisitor
# bubble/integrations/flask/detector.py

# 4. Validate against Redash
bubble flask entrypoints -d /tmp/redash-audit
bubble flask audit -d /tmp/redash-audit
```

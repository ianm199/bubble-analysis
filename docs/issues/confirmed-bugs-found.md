# Confirmed Bugs Found During Dogfooding

This document tracks real bugs found in open source projects during dogfooding of the bubble tool.

## Summary

| Project | Stars | Bugs Found | Method | Tool Worked? |
|---------|-------|------------|--------|--------------|
| **Redash** | 26k | 8 | Manual (tool missed Flask-RESTful) | ❌ |
| **Datasette** | 9.8k | 5 | Manual (tool missed ASGI) | ❌ |
| **Label Studio** | 20k | 3 | Tool + manual verification | ⚠️ Partial |
| **httpbin** | - | 1 | Tool | ✅ |

**Key insight**: The bugs are real, but we found them through manual analysis because the tool has framework coverage gaps. Fixing those gaps is the priority.

---

## Redash (26k stars) - Flask-RESTful

**Framework**: Flask with Flask-RESTful
**Tool issue**: Bubble only detected 9/60+ endpoints (missing Flask-RESTful support)

### Bug Pattern: KeyError from missing required fields

All 8 bugs follow the same pattern - handlers access `request.json["field"]` directly instead of using validation.

### Bug 1: POST /api/query_results - missing "query"
- **File**: `redash/handlers/query_results.py:160`
- **Exception**: KeyError
- **Trigger**: `curl -X POST /api/query_results -d '{}'`
- **Evidence**: Same handler uses `.get()` for optional fields

### Bug 2: POST /api/groups - missing "name"
- **File**: `redash/handlers/groups.py:12`
- **Exception**: KeyError
- **Trigger**: `curl -X POST /api/groups -d '{}'`
- **Evidence**: Other handlers use `require_fields()` for validation

### Bug 3: POST /api/groups/<id> - missing "name"
- **File**: `redash/handlers/groups.py:40`

### Bug 4: POST /api/groups/<id>/members - missing "user_id"
- **File**: `redash/handlers/groups.py:75`

### Bug 5: POST /api/groups/<id>/data_sources - missing "data_source_id"
- **File**: `redash/handlers/groups.py:126`

### Bug 6: POST /api/groups/<id>/data_sources/<id> - missing "view_only"
- **File**: `redash/handlers/groups.py:163`

### Bug 7: POST /api/widgets/<id> - missing "text" or "options"
- **File**: `redash/handlers/widgets.py:64-65`

### Bug 8: Favorites - Re-raised IntegrityError
- **File**: `redash/handlers/favorites.py:22,52`
- **Pattern**: Catches specific IntegrityError but re-raises others

---

## Datasette (9.8k stars) - ASGI

**Framework**: Custom ASGI (not Flask/FastAPI)
**Tool issue**: Bubble has no ASGI support

### Bug Pattern: Uncaught JSON parsing errors from user input

### Bug 1: _through parameter - JSONDecodeError
- **File**: `datasette/filters.py:131`
- **Trigger**: `?_through=not valid json`
- **Live test**: `curl 'https://latest.datasette.io/fixtures/facetable?_through={bad}'`

### Bug 2: _facet parameter - JSONDecodeError
- **File**: `datasette/facets.py:50`
- **Trigger**: `?_facet={invalid`

### Bug 3: column__in filter - JSONDecodeError
- **File**: `datasette/filters.py:232`
- **Trigger**: `?col__in=[broken`
- **Live test**: `curl 'https://latest.datasette.io/fixtures/facetable?state__in=[broken'`

### Bug 4: _timelimit parameter - ValueError
- **File**: `datasette/views/table.py:1198`
- **Trigger**: `?_timelimit=abc`
- **Live test**: `curl 'https://latest.datasette.io/fixtures/facetable?_timelimit=abc'`

### Bug 5: Permissions debug POST - JSONDecodeError
- **File**: `datasette/views/special.py:181`
- **Trigger**: Invalid JSON in actor field

### Evidence of inconsistency
- `special.py:565-573` DOES catch JSONDecodeError properly
- `special.py:256-260` DOES catch ValueError for page/page_size

---

## Label Studio (20k stars) - Django REST Framework

**Framework**: Django REST Framework
**Tool status**: Partially worked (found issues but route names showed as "?")

### Bug 1: DataManagerException inherits from Exception

- **File**: `label_studio/data_manager/functions.py:21-22`
- **Problem**: Uses plain `Exception` instead of DRF's `APIException`
- **Result**: All DataManagerException raises become 500 instead of 400

**5 raise sites**:
| File | Line | Message |
|------|------|---------|
| `functions.py` | 289 | "Project and View mismatch" |
| `functions.py` | 310-314 | "selectedItems must be JSON..." |
| `functions.py` | 316-319 | "selectedItems must be dict..." |
| `actions/__init__.py` | 136 | "Can't find 'X' in registered actions" |
| `actions/__init__.py` | 157 | "Can't find 'X' in registered actions" |

**Evidence**: Label Studio has `LabelStudioAPIException` (extends APIException) that SHOULD be used, and `AnnotationDuplicateError` uses it correctly.

### Bug 2 & 3: Storage Sync - KeyError escapes

- **File**: `label_studio/io_storages/api.py:129-138` (Import)
- **File**: `label_studio/io_storages/api.py:153-162` (Export)
- **Problem**: `validate_connection()` called without try/except
- **Affects**: S3, Azure, GCS, Redis, LocalFiles

**Side-by-side comparison**:
| Operation | Handling | Response |
|-----------|----------|----------|
| Create storage | try/except → ValidationError | 400 ✓ |
| Validate storage | try/except → ValidationError | 400 ✓ |
| **Sync storage** | **NONE** | **500** ✗ |

---

## httpbin - Flask

**Framework**: Flask
**Tool status**: ✅ Worked correctly

### Bug: ValueError in digest auth

- **File**: `httpbin/helpers.py:308`
- **Function**: `HA2()`
- **Trigger**: `qop=INVALID` in digest auth header
- **Live test**:
```bash
curl -i -H 'Authorization: Digest username="user", realm="test", nonce="abc", uri="/digest-auth/auth/user/passwd", qop=INVALID, nc=00000001, cnonce="xyz", response="wrong"' \
  'https://httpbin.org/digest-auth/auth/user/passwd'
```
- **Result**: 500 instead of 401

---

## Action Items

1. [ ] **Implement Flask-RESTful support** → Re-audit Redash → Verify 8 bugs found by tool
2. [ ] **Implement ASGI/Datasette support** → Re-audit Datasette → Verify 5 bugs found by tool
3. [ ] **Fix DRF route name detection** → Re-audit Label Studio → Verify clean output
4. [ ] **File issues on each project** (after tool improvements confirm the bugs)

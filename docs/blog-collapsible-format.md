## Issues found in Open Source Python Projects

| Project | Endpoints | Flagged | Confirmed |
|---------|-----------|---------|-----------|
| httpbin | 55 | 3 | **1** |
| Redash | 135 | 119 | **3** |
| Airflow | 122 | 31 | **5** |
| Label Studio | 124 | 85 | **3** |

<details>
<summary><strong>httpbin</strong> — 1 confirmed bug (click to expand)</summary>

### ValueError in Digest Authentication

**Call Stack:**
```
GET /digest-auth/auth/user/passwd
  → check_digest_auth()     helpers.py:353
    → response()            helpers.py:311
      → HA2()               helpers.py:296
        → raise ValueError  helpers.py:308
```

**User Impact:**

| Expected | Actual |
|----------|--------|
| `401 Unauthorized` | `500 Internal Server Error` |

**Why it's real:** No error handler exists. RFC 7616 requires 4xx for bad params.

**Live repro:**
```bash
curl -i -H 'Authorization: Digest username="u", realm="r", nonce="n", uri="/", qop=INVALID, nc=1, cnonce="c", response="r"' \
  https://httpbin.org/digest-auth/auth/user/passwd
```

</details>

<details>
<summary><strong>Redash</strong> — 3 confirmed bugs (click to expand)</summary>

### Bug 1: QueryDropdownsResource Missing Exception Handling

**Call Stack:**
```
GET /api/queries/123/dropdowns/456
  → QueryDropdownsResource.get()   query_results.py:204
    → dropdown_values()            query_results.py:178
      → raise QueryDetachedFromDataSourceError
```

**User Impact:**

| Expected | Actual |
|----------|--------|
| `400` with "query detached from data source" | `500 Internal Server Error` |

**Why it's real:** Same call is wrapped in try/except **10 lines earlier** in the same file:

```python
# Line 194 - CORRECT
class QueryResultDropdownResource(BaseResource):
    def get(self, query_id):
        try:
            return dropdown_values(query_id, self.current_org)
        except QueryDetachedFromDataSourceError as e:
            abort(400, message=str(e))

# Line 204 - BUG
class QueryDropdownsResource(BaseResource):
    def get(self, query_id, dropdown_query_id):
        return dropdown_values(dropdown_query_id, self.current_org)  # No try/except!
```

---

### Bug 2: ValueError in Boolean Parameter Parsing

**Call Stack:**
```
GET /api/users?disabled=invalid
  → UserListResource.get()   users.py:115
    → parse_boolean()        helpers.py:22
      → raise ValueError     helpers.py:30
```

**User Impact:**

| Expected | Actual |
|----------|--------|
| `400` with "invalid boolean value" | `500 Internal Server Error` |

**Why it's real:** Same file uses `abort(400, message="...")` for page number validation.

---

### Bug 3: KeyError on Invalid Settings

**Call Stack:**
```
POST /api/settings/organization
  → OrganizationSettings.post()   settings.py:42
    → set_setting()               organizations.py:58
      → raise KeyError            organizations.py:62
```

**User Impact:**

| Expected | Actual |
|----------|--------|
| `400` with "invalid setting key" | `500 Internal Server Error` |

**Why it's real:** Other handlers validate input with `require_fields()` first.

</details>

<details>
<summary><strong>Label Studio</strong> — 3 confirmed bugs (click to expand)</summary>

### Bug 1: Storage Sync Missing Exception Handling (10 endpoints)

**Call Stack:**
```
POST /api/storages/s3/123/sync
  → ImportStorageSyncAPI.post()     api.py:129
    → storage.validate_connection() base_models.py:298
      → raise KeyError              azure_blob/models.py:90
```

**User Impact:**

| Expected | Actual |
|----------|--------|
| `400` with "connection failed: check credentials" | `500 Internal Server Error` |

**Why it's real:** Same `validate_connection()` call is wrapped in try/except in the create endpoint (same file, line 86).

Affects: S3, Azure, GCS, Redis, LocalFiles × (import + export) = **10 endpoints**

---

### Bug 2: DataManagerException Wrong Base Class

**The Problem:**
```python
# data_manager/functions.py:21
class DataManagerException(Exception):  # Should extend APIException!
    pass
```

DRF automatically handles `APIException` subclasses. Plain `Exception` subclasses escape to 500.

**Why it's real:** The correct base class exists in the same codebase:
```python
class LabelStudioAPIException(APIException):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
```

</details>

<details>
<summary><strong>Airflow</strong> — 5 confirmed bugs (click to expand)</summary>

### Bug 1: RuntimeError from Uninitialized Auth Manager (128+ routes)

**Call Stack:**
```
GET /auth/menus
  → get_auth_menus()      auth.py:32
    → get_auth_manager()  app.py:158
      → raise RuntimeError
```

**User Impact:**

| Expected | Actual |
|----------|--------|
| `503 Service Unavailable` | `500 Internal Server Error` |

**Why it's real:** Correct pattern exists (dependency injection via `AuthManagerDep`), but 23 call sites use the wrong `get_auth_manager()` global accessor.

---

### Bug 2: TypeError in Asset Expression Parsing

**Call Stack:**
```
GET /structure_data
  → get_upstream_assets()   structure.py:37
    → raise TypeError       structure.py:69
```

**Why it's real:** User-controlled DAG definition reaches this code. Should return 400 with validation message.

---

### Bugs 3-5: ValueError in Various Routes

Multiple routes raise `ValueError` for invalid parameters but only catch `SQLAlchemyError`. Pattern exists where `ValueError` should be caught and converted to `HTTPException(400)`.

</details>

---

## The Pattern

Every confirmed bug has one thing in common: **the correct exception handling pattern already exists in the same codebase**.

The tool finds inconsistencies. Human review confirms which matter.

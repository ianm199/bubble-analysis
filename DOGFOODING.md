# Dogfooding Instructions for AI Agents

This document provides instructions for systematically testing Flow against real-world Python codebases. The goal is to validate whether Flow provides genuine value and identify gaps.

## Quick Start

```bash
# From any directory, run the dogfooding agent
cd /tmp
git clone --depth 1 <target-repo>
cd <target-repo>
bubble stats --no-cache
bubble <framework> audit  # flask, fastapi, or cli
```

## Learnings & Tips (Read This First!)

These tips come from completed dogfooding runs and will save you time:

### For Web Apps (Flask/FastAPI)
```bash
bubble stats --no-cache              # Basic metrics
bubble <framework> entrypoints       # See routes
bubble <framework> audit             # Find issues
bubble <framework> routes-to <Exc>   # Trace specific exception to routes
bubble escapes <function>            # Deep dive on specific function
```

### For Libraries (no HTTP routes)
```bash
bubble stats --no-cache              # Basic metrics
bubble exceptions                    # Exception hierarchy (very useful!)
bubble raises <Exception> -s         # Find all raises of exception + subclasses
bubble escapes <public_function>     # What can escape from public API
bubble callers <function> -r         # Who calls this, with resolution info
```

### Key Insights
- **Flow finds BUGS in web apps** - httpbin proved this (found real 500 errors)
- **Flow is a DOCUMENTATION tool for libraries** - useful for understanding exception flow, but won't find bugs (exceptions are supposed to escape)
- **Low confidence is OK for libraries** - name_fallback resolution is expected when there are no type hints
- **`bubble exceptions`** - extremely valuable for libraries, shows full hierarchy
- **`--strict` mode** - often too aggressive, filters out real findings
- **Build time** - expect ~1.5s per 1k LOC on first run
- **Always use `--depth 1`** when cloning to save time

### When to Use Flow

| Codebase Type | Flow's Value | Primary Use Case |
|---------------|--------------|------------------|
| Flask/FastAPI apps | **High** - finds real bugs | Catch uncaught exceptions before they become 500s |
| Django apps | **High** - finds real bugs | Same as Flask/FastAPI, now with `bubble django` support |
| Libraries | **Documentation only** | Generate "what can this raise?" docs |
| CLI tools | Medium | Check `if __name__ == "__main__"` error handling |

## Completed Dogfooding Results

### httpbin (Flask) ✅

**Basic Info:**
- LOC: 3,292
- Framework: Flask
- Model build time: 5.9s
- Functions detected: 167
- Entrypoints detected: 58 (55 HTTP routes, 3 CLI scripts)

**Audit Results:**
- Routes with escaping exceptions: 3 (digest-auth variants)
- Strict mode findings: 0 (too aggressive)

**Validation:**
- Route-level precision: **100%** (3/3 true positives)
- Raise-site precision: **75%** (3/4 true positives)

**Bugs Found in Flow:**
- `routes-to` command was broken (fixed in PR)
- `--strict` mode too conservative

**Real Bug Found:**
- digest-auth endpoints can return 500 errors when clients send malformed Authorization headers

**Verdict:** ✅ Yes - found real issues

---

### requests (Library) ⚠️

**Basic Info:**
- LOC: 11,152
- Framework: None (library)
- Model build time: 15s
- Functions detected: 240
- Classes detected: 45
- Entrypoints: 2 CLI scripts only

**Key Findings:**
- `bubble exceptions` correctly parsed full RequestException hierarchy (20+ exception types)
- `bubble raises RequestException -s` found all 34 raise sites
- `bubble escapes get` shows complete list of what can escape from public API

**Honest Assessment:**
Flow did NOT find any bugs here. The exceptions are *supposed* to escape - that's the library's API. For libraries, escaping exceptions is the design, not a problem.

**What Flow is good for with libraries:**
- ✅ Auto-generating "what can this function raise?" documentation
- ✅ Verifying exception hierarchy is correct
- ✅ Understanding exception flow for unfamiliar code

**What Flow is NOT good for with libraries:**
- ❌ Finding bugs (exceptions should escape to callers)
- ❌ The "audit" concept doesn't apply (no HTTP routes)

**Most Useful Commands for Libraries:**
```bash
bubble exceptions                    # Shows: RequestException -> ConnectionError -> SSLError etc
bubble raises RequestException -s    # All 34 locations where exceptions are raised
bubble escapes get                   # What can escape from requests.get()
```

**Verdict:** ⚠️ Useful as documentation/analysis tool, but NOT a bug finder for libraries

---

## Target Repositories

### Tier 1: High-Impact "Banger" Targets 🎯

These are high-profile projects where finding a bug would generate serious attention. Priority order.

| Repository | Framework | Size | Why It's a Banger | Status |
|------------|-----------|------|-------------------|--------|
| **Sentry** | Django + some Flask | Massive | Finding bugs in an *error tracker* is peak irony | 📋 TODO |
| **Airflow** | Flask | Large | Apache project, millions of users, web UI | 📋 TODO |
| **Superset** | Flask | Large | Apache project, widely-used BI tool | 📋 TODO |

#### Sentry Dogfooding Plan

```bash
# Clone (warning: large repo)
cd /tmp
git clone --depth 1 https://github.com/getsentry/sentry
cd sentry

# Sentry has multiple components - focus on the web app
cd src/sentry

# Basic analysis
bubble stats --no-cache
bubble django entrypoints      # Django routes
bubble django audit            # Find escaping exceptions

# If Django routes found, trace specific exceptions
bubble django routes-to ValidationError
bubble django routes-to PermissionDenied
bubble django routes-to ObjectDoesNotExist

# Also check their API layer (may have Flask/DRF components)
bubble flask entrypoints 2>&1 || echo "No Flask"
bubble fastapi entrypoints 2>&1 || echo "No FastAPI"
```

**What to look for:**
- Unhandled exceptions in webhook handlers (external input)
- Missing error handling in integration endpoints (GitHub, Slack, etc.)
- Exceptions in user-facing views that could leak to 500s

**Why this matters:** If you find a bug in Sentry, you can file an issue saying "I found this bug using my exception flow analyzer" - that's the kind of story that gets retweeted.

#### Airflow Dogfooding Plan

```bash
cd /tmp
git clone --depth 1 https://github.com/apache/airflow
cd airflow

# Airflow's web UI is Flask-based
cd airflow/www

bubble stats --no-cache
bubble flask entrypoints
bubble flask audit

# Trace specific exceptions
bubble flask routes-to AirflowException
bubble flask routes-to ValueError
bubble flask routes-to PermissionError

# Deep dive on interesting routes
bubble escapes trigger_dag      # DAG triggering
bubble escapes task_instance    # Task management
```

**What to look for:**
- Unhandled exceptions in DAG management endpoints
- Missing validation on user-provided DAG parameters
- Exceptions in authentication/authorization paths

**Why this matters:** Apache Airflow is used by Netflix, Airbnb, and thousands of companies. A bug found here has real-world impact.

#### Superset Dogfooding Plan

```bash
cd /tmp
git clone --depth 1 https://github.com/apache/superset
cd superset

# Superset is Flask-based
bubble stats --no-cache
bubble flask entrypoints
bubble flask audit

# Check for SQL injection-adjacent issues (exceptions from bad queries)
bubble flask routes-to SQLAlchemyError
bubble flask routes-to DatabaseError
bubble raises ProgrammingError -s

# Check authentication paths
bubble escapes login
bubble escapes oauth_authorized
```

**What to look for:**
- Unhandled database exceptions in query endpoints
- Missing validation on user-provided SQL/chart configs
- Authentication edge cases

**Why this matters:** Superset handles database credentials and runs queries - exception leaks could reveal sensitive info.

---

### Tier 2: Validation (Flask/FastAPI - known to work)

| Repository | Framework | Size | Status | Clone Command |
|------------|-----------|------|--------|---------------|
| httpbin | Flask | Small | ✅ Done | `git clone --depth 1 https://github.com/postmanlabs/httpbin` |
| Starlette | FastAPI-adjacent | Medium | 📋 TODO | `git clone --depth 1 https://github.com/encode/starlette` |
| Label Studio | Flask | Large | 📋 TODO | `git clone --depth 1 https://github.com/HumanSignal/label-studio` |

### Tier 3: Django (now supported!)

| Repository | Framework | Size | Status | Clone Command |
|------------|-----------|------|--------|---------------|
| Django REST Framework | Django | Medium | 📋 TODO | `git clone --depth 1 https://github.com/encode/django-rest-framework` |
| Zulip | Django | Large | 📋 TODO | `git clone --depth 1 https://github.com/zulip/zulip` |
| Wagtail | Django | Large | 📋 TODO | `git clone --depth 1 https://github.com/wagtail/wagtail` |
| Authentik | Django | Large | 📋 TODO | `git clone --depth 1 https://github.com/goauthentik/authentik` |
| Netbox | Django | Large | 📋 TODO | `git clone --depth 1 https://github.com/netbox-community/netbox` |

### Tier 4: Libraries (Documentation value only)

| Repository | Type | Status | Clone Command |
|------------|------|--------|---------------|
| requests | HTTP client | ✅ Done | `git clone --depth 1 https://github.com/psf/requests` |
| httpx | Async HTTP | 📋 TODO | `git clone --depth 1 https://github.com/encode/httpx` |

## Dogfooding Protocol

For each repository, follow this exact sequence:

### Step 1: Setup and Basic Metrics

```bash
# Clone and enter repo
cd /tmp
git clone <repo-url>
cd <repo-name>

# Record basic stats
echo "=== REPO: <repo-name> ===" >> /tmp/dogfood-results.md
echo "Date: $(date)" >> /tmp/dogfood-results.md

# Count lines of Python
find . -name "*.py" -not -path "./venv/*" -not -path "./.venv/*" | xargs wc -l | tail -1

# Time the model building
time flow stats
```

Record in results:
- Total Python LOC
- Model build time
- Number of functions/classes detected
- Any parse errors

### Step 2: Framework Detection

```bash
# Try each framework detector
bubble flask entrypoints 2>&1 || echo "No Flask routes found"
bubble fastapi entrypoints 2>&1 || echo "No FastAPI routes found"
bubble cli entrypoints 2>&1 || echo "No CLI scripts found"
```

Record:
- Which framework(s) detected
- Number of entrypoints found
- Any detection failures

### Step 3: Audit for Escaping Exceptions

```bash
# Run audit on detected framework
bubble <framework> audit
bubble <framework> audit --strict  # High precision mode
```

Record:
- Number of routes with escaping exceptions
- Difference between default and strict mode
- Sample of specific findings

### Step 4: Deep Dive on Specific Exceptions

```bash
# Find common exception types
bubble raises ValueError -s
bubble raises TypeError -s
bubble raises RuntimeError -s

# For web apps, check HTTP exceptions
bubble raises HTTPException -s 2>&1 || true
bubble raises NotFound -s 2>&1 || true
```

Record:
- Most common exception types raised
- Whether exception hierarchies are traced correctly

### Step 5: Trace Analysis

Pick 2-3 interesting functions from the audit and trace them:

```bash
bubble trace <function-name>
bubble escapes <function-name>
bubble escapes <function-name> --strict
```

Record:
- Does the trace look accurate?
- Are there obvious false positives?
- Are there obvious false negatives?

### Step 6: Validate Findings (Critical)

For at least 3 findings from the audit:

1. Open the source file at the reported location
2. Manually trace the code path
3. Determine if the finding is:
   - **True Positive**: Real uncaught exception that could reach users
   - **False Positive**: Exception is actually caught or can't happen
   - **Unclear**: Can't determine without runtime context

This is the most important step. Record your validation results.

## Metrics to Collect

For each repository, produce this summary:

```markdown
## <Repository Name>

**Basic Info:**
- LOC: X
- Framework: Flask/FastAPI/Django/None
- Model build time: Xs
- Functions detected: X
- Entrypoints detected: X

**Audit Results:**
- Routes with escaping exceptions: X
- Strict mode findings: X

**Validation (manual sample of N findings):**
- True positives: X
- False positives: X
- Unclear: X
- Estimated precision: X%

**Notable Issues:**
- [List any crashes, hangs, or unexpected behavior]

**Missing Patterns:**
- [List code patterns Flow failed to analyze correctly]

**Would this be useful?**
- [ ] Yes - found real issues
- [ ] Maybe - findings need investigation
- [ ] No - too noisy or missed too much
```

## Expected Outcomes

### For Flask/FastAPI repos (Tier 1):
- Should parse without errors
- Should detect routes correctly
- Audit should find real issues with <30% false positive rate

### For Django repos (Tier 2):
- Will NOT detect Django routes (expected)
- Core analysis (raises, escapes, callers) should still work
- Document what Django patterns are missed

### For Libraries (Tier 3):
- No entrypoints expected
- `bubble raises` and `bubble escapes` should work
- Test exception hierarchy tracing

## Reporting Issues

If you find bugs or gaps, create a structured report:

```markdown
### Issue: <Brief Description>

**Repository:** <name>
**Command:** `bubble <command>`
**Expected:** <what should happen>
**Actual:** <what happened>
**Reproduction:**
1. Step 1
2. Step 2

**Code sample (if applicable):**
\`\`\`python
# The code pattern that failed
\`\`\`
```

## Agent Instructions

If you are an AI agent running this dogfooding:

1. **Read the "Learnings & Tips" section first** - it will save you time
2. **Check if the repo is already done** - see status column in tables above
3. **Use `--depth 1` when cloning** - full history is not needed
4. **Time everything** - we need performance data (use `time flow stats`)
5. **Pick the right commands for the repo type:**
   - Web apps: `bubble <framework> audit` then `routes-to` for specific exceptions
   - Libraries: `bubble exceptions` then `bubble escapes <public_function>`
6. **Validate findings manually** - don't just report counts, check if they're real
7. **Be critical** - we want honest feedback, not validation
8. **Document gaps** - patterns you see that Flow misses are valuable
9. **Update this file** - add your results to "Completed Dogfooding Results" section

The goal is to answer: **"If I used this tool in CI, would it catch real bugs without too much noise?"**

### Quick Reference: Which Commands for Which Repo

| Repo Type | Primary Commands | Secondary Commands |
|-----------|------------------|-------------------|
| Flask app | `bubble flask audit`, `bubble flask routes-to <Exc>` | `bubble escapes <handler>` |
| FastAPI app | `bubble fastapi audit`, `bubble fastapi routes-to <Exc>` | `bubble escapes <handler>` |
| Django app | `bubble django audit`, `bubble django routes-to <Exc>` | `bubble escapes <view>` |
| Library | `bubble exceptions`, `bubble raises <Exc> -s` | `bubble escapes <public_func>` |

## Running the Full Suite

To run all Tier 1 repos automatically:

```bash
#!/bin/bash
REPOS=(
    "https://github.com/postmanlabs/httpbin"
    "https://github.com/encode/starlette"
)

for repo in "${REPOS[@]}"; do
    name=$(basename "$repo")
    echo "=== Testing $name ==="
    cd /tmp
    rm -rf "$name"
    git clone --depth 1 "$repo"
    cd "$name"

    echo "## $name" >> /tmp/dogfood-results.md
    echo "" >> /tmp/dogfood-results.md

    # Run flow commands and capture output
    flow stats >> /tmp/dogfood-results.md 2>&1
    flow flask audit >> /tmp/dogfood-results.md 2>&1
    flow fastapi audit >> /tmp/dogfood-results.md 2>&1

    echo "" >> /tmp/dogfood-results.md
done
```

## Success Criteria

Flow is ready for public release when:

1. **Precision > 70%** on validated findings across Tier 1 repos
2. **No crashes** on any tested repository
3. **Build time < 30s** for repos under 50k LOC
4. **At least one "real bug"** found that would have caused a user-visible error

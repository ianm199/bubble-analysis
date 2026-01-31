# Dogfooding Instructions for AI Agents

This document provides instructions for systematically testing Flow against real-world Python codebases. The goal is to validate whether Flow provides genuine value and identify gaps.

## Quick Start

```bash
# From any directory, run the dogfooding agent
cd /tmp
git clone --depth 1 <target-repo>
cd <target-repo>
flow stats --no-cache
flow <framework> audit  # flask, fastapi, or cli
```

## Learnings & Tips (Read This First!)

These tips come from completed dogfooding runs and will save you time:

### For Web Apps (Flask/FastAPI)
```bash
flow stats --no-cache              # Basic metrics
flow <framework> entrypoints       # See routes
flow <framework> audit             # Find issues
flow <framework> routes-to <Exc>   # Trace specific exception to routes
flow escapes <function>            # Deep dive on specific function
```

### For Libraries (no HTTP routes)
```bash
flow stats --no-cache              # Basic metrics
flow exceptions                    # Exception hierarchy (very useful!)
flow raises <Exception> -s         # Find all raises of exception + subclasses
flow escapes <public_function>     # What can escape from public API
flow callers <function> -r         # Who calls this, with resolution info
```

### Key Insights
- **Low confidence is OK for libraries** - name_fallback resolution is expected when there are no type hints
- **`flow exceptions`** - extremely valuable for libraries, shows full hierarchy
- **`--strict` mode** - often too aggressive, filters out real findings
- **Build time** - expect ~1.5s per 1k LOC on first run
- **Always use `--depth 1`** when cloning to save time

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

### requests (Library) ✅

**Basic Info:**
- LOC: 11,152
- Framework: None (library)
- Model build time: 15s
- Functions detected: 240
- Classes detected: 45
- Entrypoints: 2 CLI scripts only

**Key Findings:**
- `flow exceptions` correctly parsed full RequestException hierarchy (20+ exception types)
- `flow raises RequestException -s` found all 34 raise sites
- `flow escapes get` shows complete list of what can escape from public API
- All findings are "low confidence" due to name_fallback (expected for untyped library)

**Most Useful Commands for Libraries:**
```bash
flow exceptions                    # Shows: RequestException -> ConnectionError -> SSLError etc
flow raises RequestException -s    # All 34 locations where exceptions are raised
flow escapes get                   # What can escape from requests.get()
```

**Verdict:** ✅ Yes - useful for library authors documenting exception behavior

---

## Target Repositories

### Tier 1: Validation (Flask/FastAPI - should work)

| Repository | Framework | Size | Status | Clone Command |
|------------|-----------|------|--------|---------------|
| httpbin | Flask | Small | ✅ Done | `git clone --depth 1 https://github.com/postmanlabs/httpbin` |
| Starlette | FastAPI-adjacent | Medium | 📋 TODO | `git clone --depth 1 https://github.com/encode/starlette` |
| Label Studio | Flask | Large | 📋 TODO | `git clone --depth 1 https://github.com/HumanSignal/label-studio` |

### Tier 2: Gap Analysis (Django - not yet supported)

| Repository | Framework | Size | Status | Clone Command |
|------------|-----------|------|--------|---------------|
| Django REST Framework | Django | Medium | 📋 TODO | `git clone --depth 1 https://github.com/encode/django-rest-framework` |
| Zulip | Django | Large | 📋 TODO | `git clone --depth 1 https://github.com/zulip/zulip` |
| Wagtail | Django | Large | 📋 TODO | `git clone --depth 1 https://github.com/wagtail/wagtail` |

### Tier 3: Libraries (Exception-heavy)

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
flow flask entrypoints 2>&1 || echo "No Flask routes found"
flow fastapi entrypoints 2>&1 || echo "No FastAPI routes found"
flow cli entrypoints 2>&1 || echo "No CLI scripts found"
```

Record:
- Which framework(s) detected
- Number of entrypoints found
- Any detection failures

### Step 3: Audit for Escaping Exceptions

```bash
# Run audit on detected framework
flow <framework> audit
flow <framework> audit --strict  # High precision mode
```

Record:
- Number of routes with escaping exceptions
- Difference between default and strict mode
- Sample of specific findings

### Step 4: Deep Dive on Specific Exceptions

```bash
# Find common exception types
flow raises ValueError -s
flow raises TypeError -s
flow raises RuntimeError -s

# For web apps, check HTTP exceptions
flow raises HTTPException -s 2>&1 || true
flow raises NotFound -s 2>&1 || true
```

Record:
- Most common exception types raised
- Whether exception hierarchies are traced correctly

### Step 5: Trace Analysis

Pick 2-3 interesting functions from the audit and trace them:

```bash
flow trace <function-name>
flow escapes <function-name>
flow escapes <function-name> --strict
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
- `flow raises` and `flow escapes` should work
- Test exception hierarchy tracing

## Reporting Issues

If you find bugs or gaps, create a structured report:

```markdown
### Issue: <Brief Description>

**Repository:** <name>
**Command:** `flow <command>`
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
   - Web apps: `flow <framework> audit` then `routes-to` for specific exceptions
   - Libraries: `flow exceptions` then `flow escapes <public_function>`
6. **Validate findings manually** - don't just report counts, check if they're real
7. **Be critical** - we want honest feedback, not validation
8. **Document gaps** - patterns you see that Flow misses are valuable
9. **Update this file** - add your results to "Completed Dogfooding Results" section

The goal is to answer: **"If I used this tool in CI, would it catch real bugs without too much noise?"**

### Quick Reference: Which Commands for Which Repo

| Repo Type | Primary Commands | Secondary Commands |
|-----------|------------------|-------------------|
| Flask app | `flow flask audit`, `flow flask routes-to <Exc>` | `flow escapes <handler>` |
| FastAPI app | `flow fastapi audit`, `flow fastapi routes-to <Exc>` | `flow escapes <handler>` |
| Library | `flow exceptions`, `flow raises <Exc> -s` | `flow escapes <public_func>` |
| Django app | `flow raises <Exc>`, `flow escapes <view>` | Document missing patterns |

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

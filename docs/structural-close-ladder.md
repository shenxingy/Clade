[EN] | [Back to README](../README.md)

# Structural Close Ladder

When a fix patch alone is insufficient — the same defect shape recurs, or the
type system can be made to prevent the class of bug permanently — escalate
through the following templates (lovesegfault N=4..7). Each level is stronger
than the last; stop at the first level that closes the structural gap.

---

## N=4 — Delete the Re-implementation

**Signal**: A second copy of the same logic exists alongside the canonical one.
The fix landed on one copy; the other still carries the old shape.

**Template**:
1. `grep -rn "<pattern>"` — enumerate every site that duplicates the logic.
2. For each duplicate: replace with a call to the canonical function, or inline
   the canonical logic if that is simpler.
3. Delete the duplicate definition. If it is exported, update callers.
4. **Done-gate**: `grep -rn "<pattern>"` returns only the canonical definition.

**Example**: Two `parse_date()` functions in `utils/` and `models/`. The bug
was in the `models/` copy. Delete `models/parse_date`, update callers to use
`utils/parse_date`.

---

## N=5 — Make the Function Total

**Signal**: The function raises / returns a sentinel on an input the caller
will inevitably supply. The bug was a partial function; the fix was a guard
that the next caller will also forget.

**Template**:
1. Identify every input class the function does not handle (raise / None return).
2. Extend the return type or add a documented contract:
   - Return a `Result`/`Optional` and update callers to unwrap, **or**
   - Add a precondition assertion at the top and document it in the docstring.
3. Audit all existing callers: each must handle the new return type or prove
   the precondition holds at its call site.
4. **Done-gate**: `mypy`/`pyright` passes with no `Any` suppressions around
   this function's return value; no caller silently ignores `None`.

**Example**: `lookup_user(id)` returns `None` on missing user but callers use
`user.name` without a guard. Add `-> User | None`, update every caller.

---

## N=6a — Single Emit Chokepoint

**Signal**: The same value is written/emitted/serialized in multiple places.
A fix to one site leaves the others stale.

**Template**:
1. Identify all emit sites for the value (grep for the field name / event key).
2. Extract a single canonical emitter (function or method). Route all sites
   through it.
3. Remove the now-dead direct emit code from every non-canonical site.
4. **Done-gate**: `grep -rn "<emit pattern>"` returns only the canonical
   emitter and its callers (not raw writes).

**Example**: `status: "running"` string is set in `worker.py`, `session.py`,
and `api.py`. Extract `_set_status(task_id, status)` and call it from all
three.

---

## N=6b — Newtype Split

**Signal**: Two distinct logical values share the same primitive type. The bug
was a mix-up — a raw string used where a validated/escaped string was required,
or a user ID passed where a session ID was expected.

**Template**:
1. Define a newtype or wrapper class for the restricted value:
   ```python
   # Python
   from typing import NewType
   UserId = NewType("UserId", str)
   SessionId = NewType("SessionId", str)
   ```
   ```rust
   // Rust
   struct UserId(String);
   struct SessionId(String);
   ```
2. Update the function signatures that receive or return these values.
3. Fix every type error the compiler/type-checker now reports.
4. **Done-gate**: No `cast()`/`# type: ignore` suppressions remain around
   the affected parameter.

**Example**: `create_session(user_id: str)` was called with a `session_id` by
mistake. Split into `UserId` and `SessionId`; the compiler catches future
mix-ups.

---

## N=7 — Precondition → Postcondition Contract

**Signal**: The fix is a runtime guard (assert / early return). The same guard
has been added before, or the invariant is complex enough that future code will
re-break it.

**Template**:
1. Write the invariant as a formal docstring contract or a property-based test:
   ```python
   def process(data: Data) -> Result:
       """
       Pre:  data.field is not None and data.field > 0
       Post: result.value == data.field * FACTOR
       """
   ```
2. Add a property test (hypothesis / proptest) covering the boundary inputs
   that triggered the bug.
3. If the language supports it, encode the precondition in the type (see N=6b).
4. **Done-gate**: Property test covers the failing input; CI runs it on every
   push.

**Example**: `compute_score(weight)` crashed when `weight=0`. Add
`assert weight > 0, "weight must be positive"` + a hypothesis test
`@given(st.floats(min_value=0.0, exclude_min=True))`.

---

## Choosing the Right Level

| Symptom | Start at |
|---------|----------|
| Same fix needed in 2+ places | N=4 (delete re-impl) |
| Guard added for the 2nd time | N=5 (make total) |
| Value written in 3+ places | N=6a (chokepoint) |
| Type confusion / wrong-id bug | N=6b (newtype) |
| Invariant is subtle, will recur | N=7 (contract) |

Stop escalating when the structural gap is closed — not every bug needs N=7.

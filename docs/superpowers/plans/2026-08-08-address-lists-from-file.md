# Address Lists From a File — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each of the three address fields — recipient (To), from, and journal — independently draw from its own per-field address-list file, in any combination.

**Architecture:** Follows the existing plan-object idiom in `smtpbench/cli.py` (`BodyPlan`/`build_body_plan`, `AttachmentPlan`/`build_attachment_plan`): parse a file once at startup into an `AddressList` object stored in a module global, then select one address per message via the already-seeded per-message RNG in `send_email()`. A single field-agnostic `AddressList` class serves all three fields; round-robin state lives inside each instance under its own lock, keeping the three fields independent.

**Tech Stack:** Python 3.9+, stdlib only (`random`, `threading`, `os`). Tests: `pytest` (`-m "not integration"` for unit, `-m integration` for Docker). Lint/format: `ruff`.

## Global Constraints

- **No version bump.** Fold into the unreleased `## [1.2.0]` CHANGELOG section. `pyproject.toml` and `smtpbench/__init__.py` stay at `1.2.0`.
- **Single-file app.** All runtime code lives in `smtpbench/cli.py`; module-global state mutated across threads under the single `threading.Lock` named `lock`. New module globals that affect test outcomes MUST be reset in `tests/conftest.py`'s autouse `reset_globals` fixture (both the before-`yield` and after-`yield` blocks).
- **`key=value` parsing.** No argparse. Booleans are strings compared with `.lower() == "true"`. Presence of a key enables a mode.
- **Fail-fast at startup.** All configuration validation happens in `main()` before any worker thread starts, and prints `f"{Fore.RED}✗ ...{Style.RESET_ALL}"` then `sys.exit(1)` — matching the existing attachment/credential/rate error style.
- **Multi-`@` invariant.** An address is valid iff `addr.split("@")` yields exactly 2 non-empty parts (the rule `mx_lookup_all` enforces at `cli.py:264-267`). Applied to every address in every file.
- **Content/metadata split preserved.** Raw bytes still flow only to `create_message`; only metadata flows to logs/summary. Addresses are not credentials — no redaction — but do not dump full address lists into the summary JSON (metadata only: filename, count, order).
- **Ruff clean.** `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .` must pass. Rules: `E, F, I, W, UP`, `E501` ignored.
- **Use the venv explicitly** in all commands: `.venv/bin/python`, `.venv/bin/pytest` (or `.venv/bin/python -m pytest`), `.venv/bin/ruff`. Bare `python`/`ruff`/`pytest` are not on PATH.

---

## File Structure

| File | Responsibility | Change |
| --- | --- | --- |
| `smtpbench/cli.py` | `AddressList` class, `parse_address_file`, `build_address_list`, three module globals, `main()` validation + wiring, `send_email` selection, `log_json` fields, summary block, help/usage text | Modify |
| `tests/conftest.py` | Reset the three new globals | Modify |
| `tests/test_smtpbench.py` | Unit tests for parsing, selection, builder, validation matrix, determinism | Modify |
| `README.md` | "Address lists from a file" subsection | Modify |
| `CHANGELOG.md` | Fold into unreleased `## [1.2.0]` Added | Modify |

The three globals `recipient_list`, `from_list`, `journal_list` live beside the existing `attachment_plan`/`body_plan` globals (`cli.py:52-53`).

---

## Task 1: `AddressList` class

**Files:**
- Modify: `smtpbench/cli.py` (add class next to `BodyPlan`, ~line 631)
- Test: `tests/test_smtpbench.py` (new class `TestAddressList`)

**Interfaces:**
- Consumes: nothing (uses stdlib `random`, `threading`).
- Produces: `class AddressList` with `__init__(self, addresses, order)` where `addresses: list[str]` (non-empty), `order: str` in `{"random", "roundrobin"}`; and `select(self, rng) -> str`. Random mode returns `rng.choice(self.addresses)`; round-robin returns addresses cyclically under a per-instance lock. Later tasks call `select(rng)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_smtpbench.py`:

```python
class TestAddressList:
    def test_random_is_deterministic_for_seeded_rng(self):
        import random
        from smtpbench.cli import AddressList

        addrs = ["a@x.com", "b@x.com", "c@x.com"]
        plan = AddressList(addrs, "random")
        rng1 = random.Random("seed-1")
        rng2 = random.Random("seed-1")
        picks1 = [plan.select(rng1) for _ in range(10)]
        picks2 = [plan.select(rng2) for _ in range(10)]
        assert picks1 == picks2
        assert all(p in addrs for p in picks1)

    def test_roundrobin_cycles_evenly_and_wraps(self):
        from smtpbench.cli import AddressList

        addrs = ["a@x.com", "b@x.com", "c@x.com"]
        plan = AddressList(addrs, "roundrobin")
        # RNG is unused in roundrobin mode; pass a dummy.
        picks = [plan.select(rng=None) for _ in range(7)]
        assert picks == [
            "a@x.com", "b@x.com", "c@x.com",
            "a@x.com", "b@x.com", "c@x.com",
            "a@x.com",
        ]

    def test_roundrobin_instances_have_independent_counters(self):
        from smtpbench.cli import AddressList

        p1 = AddressList(["a@x.com", "b@x.com"], "roundrobin")
        p2 = AddressList(["c@x.com", "d@x.com"], "roundrobin")
        assert p1.select(None) == "a@x.com"
        assert p2.select(None) == "c@x.com"   # p2 not advanced by p1
        assert p1.select(None) == "b@x.com"
        assert p2.select(None) == "d@x.com"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_smtpbench.py::TestAddressList -v`
Expected: FAIL with `ImportError`/`AttributeError` (no `AddressList`).

- [ ] **Step 3: Implement `AddressList`**

In `smtpbench/cli.py`, immediately before `class BodyPlan:` (~line 631), add:

```python
class AddressList:
    """Per-message address selection from a parsed list of addresses.

    order="random":     rng.choice per message (reproducible for a fixed seed).
    order="roundrobin": cycle the list evenly across the whole run; the shared
                        index is guarded by a per-instance lock, so the three
                        address fields' round-robin counters stay independent.
    """

    def __init__(self, addresses, order):
        self.addresses = addresses  # non-empty list[str]
        self.order = order  # "random" | "roundrobin"
        self._idx = 0
        self._lock = threading.Lock()

    def select(self, rng):
        if self.order == "roundrobin":
            with self._lock:
                addr = self.addresses[self._idx % len(self.addresses)]
                self._idx += 1
            return addr
        return rng.choice(self.addresses)
```

`threading` and `random` are already imported at the top of `cli.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_smtpbench.py::TestAddressList -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add smtpbench/cli.py tests/test_smtpbench.py
git commit -m "feat: AddressList per-message selection (random + roundrobin)"
```

---

## Task 2: `parse_address_file`

**Files:**
- Modify: `smtpbench/cli.py` (add after `AddressList`, before `BodyPlan`)
- Test: `tests/test_smtpbench.py` (new class `TestParseAddressFile`)

**Interfaces:**
- Consumes: nothing.
- Produces: `parse_address_file(path, field_label) -> list[str]`. Reads one address per line, strips whitespace, skips blank lines and lines starting with `#`, validates each remaining address with the multi-`@` rule. Raises `FileNotFoundError` if the path is missing, `ValueError` if no valid addresses remain, and `ValueError` naming the file + 1-based line number + offending value if any address has `!= 1` non-empty `@`-part. `field_label` (e.g. `"recipient"`) is only used in error messages.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_smtpbench.py`:

```python
class TestParseAddressFile:
    def test_parses_one_per_line_skips_blanks_and_comments(self, tmp_path):
        from smtpbench.cli import parse_address_file

        f = tmp_path / "list.txt"
        f.write_text(
            "# primary\n"
            "alice@example.com\n"
            "\n"
            "  bob@example.com  \n"
            "# trailing comment\n"
            "carol@example.com\n"
        )
        assert parse_address_file(str(f), "recipient") == [
            "alice@example.com",
            "bob@example.com",
            "carol@example.com",
        ]

    def test_missing_file_raises(self, tmp_path):
        from smtpbench.cli import parse_address_file

        with pytest.raises(FileNotFoundError):
            parse_address_file(str(tmp_path / "nope.txt"), "recipient")

    def test_empty_after_filtering_raises(self, tmp_path):
        from smtpbench.cli import parse_address_file

        f = tmp_path / "empty.txt"
        f.write_text("# only comments\n\n   \n")
        with pytest.raises(ValueError, match="no valid addresses"):
            parse_address_file(str(f), "from")

    def test_multi_at_address_raises_with_file_and_line(self, tmp_path):
        from smtpbench.cli import parse_address_file

        f = tmp_path / "bad.txt"
        f.write_text("alice@example.com\nbob@@example.com\n")
        with pytest.raises(ValueError, match="line 2"):
            parse_address_file(str(f), "recipient")

    def test_no_at_address_raises(self, tmp_path):
        from smtpbench.cli import parse_address_file

        f = tmp_path / "bad.txt"
        f.write_text("not-an-email\n")
        with pytest.raises(ValueError):
            parse_address_file(str(f), "journal")
```

`pytest` is already imported at the top of `tests/test_smtpbench.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_smtpbench.py::TestParseAddressFile -v`
Expected: FAIL (`parse_address_file` undefined).

- [ ] **Step 3: Implement `parse_address_file`**

In `smtpbench/cli.py`, after the `AddressList` class:

```python
def _is_valid_address(addr):
    """Exactly one '@' with non-empty local and domain parts (the invariant
    mx_lookup_all enforces on the single recipient)."""
    parts = addr.split("@")
    return len(parts) == 2 and bool(parts[0]) and bool(parts[1])


def parse_address_file(path, field_label):
    """Read one address per line. Strip whitespace; skip blank lines and lines
    beginning with '#'. Validate every remaining address (exactly one '@').
    Raise FileNotFoundError if missing, ValueError if no valid addresses remain
    or any address is malformed (message names the file, 1-based line, value)."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"{field_label} address file not found: {path}")
    addresses = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if not _is_valid_address(line):
                raise ValueError(
                    f"Invalid {field_label} address in {path} line {lineno}: {line!r}"
                )
            addresses.append(line)
    if not addresses:
        raise ValueError(f"{field_label} address file has no valid addresses: {path}")
    return addresses
```

`os` is already imported.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_smtpbench.py::TestParseAddressFile -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add smtpbench/cli.py tests/test_smtpbench.py
git commit -m "feat: parse_address_file (one-per-line, comments, validation)"
```

---

## Task 3: `build_address_list`

**Files:**
- Modify: `smtpbench/cli.py` (add after `parse_address_file`)
- Test: `tests/test_smtpbench.py` (new class `TestBuildAddressList`)

**Interfaces:**
- Consumes: `AddressList` (Task 1), `parse_address_file` (Task 2).
- Produces: `build_address_list(args, field) -> AddressList | None` where `field` is one of `"recipient"`, `"from"`, `"journal"`. Returns `None` when `f"{field}_file"` is absent from `args`. Otherwise reads `f"{field}_file"` (path) and `f"{field}_file_order"` (default `"random"`, must be `"random"` or `"roundrobin"` else `ValueError`), parses the file, and returns an `AddressList`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_smtpbench.py`:

```python
class TestBuildAddressList:
    def test_absent_key_returns_none(self):
        from smtpbench.cli import build_address_list

        assert build_address_list({}, "recipient") is None

    def test_builds_with_default_random_order(self, tmp_path):
        from smtpbench.cli import build_address_list

        f = tmp_path / "r.txt"
        f.write_text("a@x.com\nb@x.com\n")
        plan = build_address_list({"recipient_file": str(f)}, "recipient")
        assert plan is not None
        assert plan.order == "random"
        assert plan.addresses == ["a@x.com", "b@x.com"]

    def test_reads_explicit_order(self, tmp_path):
        from smtpbench.cli import build_address_list

        f = tmp_path / "s.txt"
        f.write_text("a@x.com\n")
        plan = build_address_list(
            {"from_file": str(f), "from_file_order": "roundrobin"}, "from"
        )
        assert plan.order == "roundrobin"

    def test_invalid_order_raises(self, tmp_path):
        from smtpbench.cli import build_address_list

        f = tmp_path / "j.txt"
        f.write_text("a@x.com\n")
        with pytest.raises(ValueError, match="roundrobin"):
            build_address_list(
                {"journal_file": str(f), "journal_file_order": "sideways"}, "journal"
            )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_smtpbench.py::TestBuildAddressList -v`
Expected: FAIL (`build_address_list` undefined).

- [ ] **Step 3: Implement `build_address_list`**

In `smtpbench/cli.py`, after `parse_address_file`:

```python
ADDRESS_FILE_ORDERS = ("random", "roundrobin")


def build_address_list(args, field):
    """Build an AddressList for one field ('recipient'|'from'|'journal') from
    '<field>_file' and '<field>_file_order' (default 'random'), or None if the
    '<field>_file' key is absent."""
    path = args.get(f"{field}_file")
    if not path:
        return None
    order = args.get(f"{field}_file_order", "random")
    if order not in ADDRESS_FILE_ORDERS:
        raise ValueError(
            f"Invalid {field}_file_order '{order}'; valid values: "
            f"{', '.join(ADDRESS_FILE_ORDERS)}"
        )
    addresses = parse_address_file(path, field)
    return AddressList(addresses, order)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_smtpbench.py::TestBuildAddressList -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add smtpbench/cli.py tests/test_smtpbench.py
git commit -m "feat: build_address_list from *_file / *_file_order args"
```

---

## Task 4: Module globals + conftest reset

**Files:**
- Modify: `smtpbench/cli.py:52-53` (add three globals)
- Modify: `tests/conftest.py` (reset them in both blocks)
- Test: `tests/test_smtpbench.py` (extend an existing import-smoke or add `test_address_list_globals_default_none`)

**Interfaces:**
- Consumes: nothing.
- Produces: module globals `cli.recipient_list`, `cli.from_list`, `cli.journal_list`, each defaulting to `None`. Later tasks (`send_email`, `main`) read/assign these.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_smtpbench.py` (e.g. in a `TestModuleGlobals` class, or alongside other global checks):

```python
class TestAddressListGlobals:
    def test_globals_default_none(self):
        from smtpbench import cli

        assert cli.recipient_list is None
        assert cli.from_list is None
        assert cli.journal_list is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_smtpbench.py::TestAddressListGlobals -v`
Expected: FAIL (`AttributeError`: globals don't exist yet).

- [ ] **Step 3: Add the globals and conftest resets**

In `smtpbench/cli.py`, after `body_plan = None  # ...` (line 53), add:

```python
recipient_list = None  # AddressList or None, built once in main()
from_list = None  # AddressList or None, built once in main()
journal_list = None  # AddressList or None, built once in main()
```

In `tests/conftest.py`, add these three lines to **both** the before-`yield` block (after `cli.body_plan = None`, line 25) and the after-`yield` block (after `cli.body_plan = None`, line 43):

```python
    cli.recipient_list = None
    cli.from_list = None
    cli.journal_list = None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_smtpbench.py::TestAddressListGlobals -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add smtpbench/cli.py tests/conftest.py tests/test_smtpbench.py
git commit -m "feat: address-list module globals + conftest reset"
```

---

## Task 5: Startup validation in `main()`

**Files:**
- Modify: `smtpbench/cli.py` `main()` — insert a validation + build block after the body_plan build (~line 1181) and before `setup_logging()`; also relax the required-key check for `recipient`.
- Test: `tests/test_smtpbench.py` (new class `TestAddressListValidation`)

**Interfaces:**
- Consumes: `build_address_list` (Task 3), the globals (Task 4).
- Produces: a `validate_address_list_args(args, offline_mode)` helper that raises `ValueError` on any rule violation (so it is unit-testable without invoking full `main()`), plus `main()` wiring that assigns `recipient_list`/`from_list`/`journal_list` globals and `sys.exit(1)`s on `ValueError`. Rules enforced (all from the spec's error table):
  - `recipient_file` + `recipient` both set → error
  - `from_file` + `from_address` both set → error
  - `journal_file` + `journal_address` both set → error
  - neither `recipient` nor `recipient_file` → error
  - `recipient_file` without `lb_host` and not offline → error
  - `journal_file` without `journal=true` → error
  - any `*_file_order` present without its `*_file` → error

Note: invalid order *values* and file parse errors are already raised by `build_address_list`/`parse_address_file` (Tasks 2-3); this task adds the *cross-argument* rules.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_smtpbench.py`:

```python
class TestAddressListValidation:
    def _mk(self, tmp_path, name="l.txt", body="a@x.com\nb@x.com\n"):
        f = tmp_path / name
        f.write_text(body)
        return str(f)

    def test_recipient_file_and_recipient_conflict(self, tmp_path):
        from smtpbench.cli import validate_address_list_args

        args = {"recipient": "x@y.com", "recipient_file": self._mk(tmp_path),
                "lb_host": "relay"}
        with pytest.raises(ValueError, match="recipient_file"):
            validate_address_list_args(args, offline_mode=False)

    def test_from_file_and_from_address_conflict(self, tmp_path):
        from smtpbench.cli import validate_address_list_args

        args = {"recipient": "x@y.com", "from_file": self._mk(tmp_path),
                "from_address": "s@y.com"}
        with pytest.raises(ValueError, match="from_file"):
            validate_address_list_args(args, offline_mode=False)

    def test_journal_file_and_journal_address_conflict(self, tmp_path):
        from smtpbench.cli import validate_address_list_args

        args = {"recipient": "x@y.com", "journal": "true",
                "journal_file": self._mk(tmp_path), "journal_address": "j@y.com"}
        with pytest.raises(ValueError, match="journal_file"):
            validate_address_list_args(args, offline_mode=False)

    def test_neither_recipient_nor_recipient_file(self, tmp_path):
        from smtpbench.cli import validate_address_list_args

        with pytest.raises(ValueError, match="recipient"):
            validate_address_list_args({}, offline_mode=False)

    def test_recipient_file_requires_lb_host_or_offline(self, tmp_path):
        from smtpbench.cli import validate_address_list_args

        args = {"recipient_file": self._mk(tmp_path)}
        with pytest.raises(ValueError, match="lb_host"):
            validate_address_list_args(args, offline_mode=False)

    def test_recipient_file_ok_with_lb_host(self, tmp_path):
        from smtpbench.cli import validate_address_list_args

        args = {"recipient_file": self._mk(tmp_path), "lb_host": "relay"}
        validate_address_list_args(args, offline_mode=False)  # no raise

    def test_recipient_file_ok_offline_without_lb_host(self, tmp_path):
        from smtpbench.cli import validate_address_list_args

        args = {"recipient_file": self._mk(tmp_path)}
        validate_address_list_args(args, offline_mode=True)  # no raise

    def test_journal_file_requires_journal_true(self, tmp_path):
        from smtpbench.cli import validate_address_list_args

        args = {"recipient": "x@y.com", "journal_file": self._mk(tmp_path)}
        with pytest.raises(ValueError, match="journal=true"):
            validate_address_list_args(args, offline_mode=False)

    def test_orphan_order_key_raises(self, tmp_path):
        from smtpbench.cli import validate_address_list_args

        args = {"recipient": "x@y.com", "from_file_order": "random"}
        with pytest.raises(ValueError, match="from_file_order"):
            validate_address_list_args(args, offline_mode=False)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_smtpbench.py::TestAddressListValidation -v`
Expected: FAIL (`validate_address_list_args` undefined).

- [ ] **Step 3: Implement `validate_address_list_args`**

In `smtpbench/cli.py`, add near `build_address_list`:

```python
def validate_address_list_args(args, offline_mode):
    """Enforce the cross-argument rules for address-list files. Raises
    ValueError on any violation. (Per-file parse errors and invalid order
    values are raised separately by build_address_list/parse_address_file.)"""
    conflicts = [
        ("recipient_file", "recipient"),
        ("from_file", "from_address"),
        ("journal_file", "journal_address"),
    ]
    for file_key, single_key in conflicts:
        if file_key in args and single_key in args:
            raise ValueError(
                f"{file_key} and {single_key} are mutually exclusive; use one."
            )

    if "recipient" not in args and "recipient_file" not in args:
        raise ValueError("Provide recipient= or recipient_file=.")

    if "recipient_file" in args and not offline_mode and "lb_host" not in args:
        raise ValueError(
            "recipient_file requires lb_host= (a fixed relay) or eml_out_dir= "
            "(offline output); a multi-domain recipient file has no single MX target."
        )

    if "journal_file" in args and args.get("journal", "false").lower() != "true":
        raise ValueError("journal_file requires journal=true.")

    for field in ("recipient", "from", "journal"):
        if f"{field}_file_order" in args and f"{field}_file" not in args:
            raise ValueError(
                f"{field}_file_order was given without {field}_file."
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_smtpbench.py::TestAddressListValidation -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Wire into `main()`**

Two edits in `main()`:

(a) The `recipient` required-key check must not fire when `recipient_file` is present. Change the required list at `cli.py:1100` from:

```python
    required = ["recipient", "port", "threads", "messages"]
    missing = [key for key in required if key not in args]
```

to:

```python
    required = ["port", "threads", "messages"]
    missing = [key for key in required if key not in args]
    if "recipient" not in args and "recipient_file" not in args:
        missing.append("recipient")
```

Leave the `missing` error block below it unchanged (it already prints the required-parameter help and exits).

(b) `recipient = args["recipient"]` at `cli.py:1119` assumes the key exists. Change it to tolerate `recipient_file`-only runs:

```python
    recipient = args.get("recipient")
```

Then, immediately after the `body_plan` build block (after `cli.py:1181`, before `loggers = setup_logging()`), insert:

```python
    try:
        validate_address_list_args(args, offline_mode)
        recipient_list = build_address_list(args, "recipient")
        from_list = build_address_list(args, "from")
        journal_list = build_address_list(args, "journal")
    except (ValueError, FileNotFoundError) as e:
        print(f"{Fore.RED}✗ Address list configuration error: {e}{Style.RESET_ALL}")
        sys.exit(1)
```

Add `recipient_list`, `from_list`, `journal_list` to the `global` declaration at the top of `main()` (the block spanning `cli.py:1081-1096`, alongside `attachment_plan`, `body_plan`, etc.).

**Guard the MX/offline block for `recipient_file`-only runs.** The block at `cli.py:1119-1129` calls `mx_lookup_all(recipient)` when not offline and no `lb_host`. With validation in place, a `recipient_file` run always has `lb_host` or offline, so `mx_lookup_all(None)` is unreachable — but `recipient` may now be `None`. `journal_address = args.get("journal_address", recipient)` (line 1160) would then default to `None`, which is fine (journal disabled or journal_list used). No further change needed; confirm by running the full suite in Step 6.

- [ ] **Step 6: Run the full unit suite to verify no regressions**

Run: `.venv/bin/python -m pytest -v -m "not integration"`
Expected: PASS (all prior tests + the new validation tests).

- [ ] **Step 7: Commit**

```bash
git add smtpbench/cli.py tests/test_smtpbench.py
git commit -m "feat: address-list startup validation + main() wiring"
```

---

## Task 6: Per-message selection in `send_email` + logging

**Files:**
- Modify: `smtpbench/cli.py` `send_email` (~line 839-914) and `log_json` (line 226-259)
- Test: `tests/test_smtpbench.py` (new class `TestAddressSelectionInSend` + `TestLogJsonAddressFields`)

**Interfaces:**
- Consumes: the three globals (Task 4), `AddressList.select` (Task 1).
- Produces: `send_email` uses effective recipient/from/journal per message; `log_json` gains `from_used=None` and `journal_used=None` keyword params, emitted in the entry dict.

- [ ] **Step 1: Write the failing tests**

> **Before writing `TestAddressSelectionInSend`:** read `send_email`'s actual signature in `smtpbench/cli.py` (~line 825) and match the keyword names/order below to it. The call in the test is illustrative; the real parameter names (`retry_delay`, `max_retries`, `progress_bar`, `tls_mode`, `transaction_timeout`, etc.) must match exactly or the test fails for the wrong reason.

Add to `tests/test_smtpbench.py`:

```python
class TestLogJsonAddressFields:
    def test_log_json_includes_from_and_journal_used(self):
        import json
        from unittest.mock import Mock
        from smtpbench.cli import log_json

        logger = Mock()
        log_json(
            logger, "success", 1, 1, 0.5,
            from_used="s@x.com", journal_used="j@x.com",
        )
        entry = json.loads(logger.info.call_args[0][0])
        assert entry["from_used"] == "s@x.com"
        assert entry["journal_used"] == "j@x.com"

    def test_log_json_address_fields_default_none(self):
        import json
        from unittest.mock import Mock
        from smtpbench.cli import log_json

        logger = Mock()
        log_json(logger, "success", 1, 1, 0.5)
        entry = json.loads(logger.info.call_args[0][0])
        assert entry["from_used"] is None
        assert entry["journal_used"] is None


class TestAddressSelectionInSend:
    def test_effective_addresses_come_from_lists_offline(self, tmp_path):
        """In offline mode, send_email writes an EML whose From/To reflect the
        per-message picks from the address lists."""
        import email
        from smtpbench import cli
        from smtpbench.cli import AddressList

        cli.offline_mode = True
        cli.eml_out_dir = str(tmp_path)
        cli.recipient_list = AddressList(["to@x.com"], "roundrobin")
        cli.from_list = AddressList(["sender@x.com"], "roundrobin")

        from unittest.mock import Mock
        loggers = {"success": Mock(), "fail": Mock(), "retry": Mock(), "debug": Mock()}
        progress = Mock()

        cli.send_email(
            port=587, recipient="fallback@x.com", from_address="fallback-from@x.com",
            thread_id=1, message_id=1, retry_delay=0, loggers=loggers,
            tls_mode="none", transaction_timeout=5, max_retries=0,
            progress_bar=progress,
        )

        eml_files = list(tmp_path.glob("*.eml"))
        assert len(eml_files) == 1
        msg = email.message_from_bytes(eml_files[0].read_bytes())
        assert msg["To"] == "to@x.com"
        assert msg["From"] == "sender@x.com"

    def test_random_mode_selection_is_reproducible_across_runs(self, tmp_path):
        """Spec: with all three fields in random mode, a fixed run_uuid +
        thread/message yields the same three picks. This locks the RNG draw
        order (attachments -> body -> recipient -> from -> journal) so adding
        the address draws never perturbs reproducibility."""
        import email
        from unittest.mock import Mock
        from smtpbench import cli
        from smtpbench.cli import AddressList

        def run_once(out_dir):
            cli.offline_mode = True
            cli.eml_out_dir = str(out_dir)
            cli.run_uuid = "fixed-run-uuid"
            cli.journal_enabled = True
            cli.recipient_list = AddressList(
                ["r1@x.com", "r2@x.com", "r3@x.com"], "random"
            )
            cli.from_list = AddressList(["f1@x.com", "f2@x.com"], "random")
            cli.journal_list = AddressList(["j1@x.com", "j2@x.com"], "random")
            loggers = {k: Mock() for k in ("success", "fail", "retry", "debug")}
            cli.send_email(
                port=587, recipient="fallback@x.com",
                from_address="fallback-from@x.com", thread_id=3, message_id=7,
                retry_delay=0, loggers=loggers, tls_mode="none",
                transaction_timeout=5, max_retries=0, progress_bar=Mock(),
            )
            eml = list(out_dir.glob("*.eml"))[0]
            m = email.message_from_bytes(eml.read_bytes())
            return (m["To"], m["From"])

        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        assert run_once(a) == run_once(b)
```

Note: the `run_uuid`/`journal_enabled` globals are reset by conftest, so the two `run_once` calls each set them explicitly. If `send_email` seeds its rng from `run_uuid` plus thread/message (it does, at ~line 841), fixing all three makes the two runs draw identically.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_smtpbench.py::TestLogJsonAddressFields tests/test_smtpbench.py::TestAddressSelectionInSend -v`
Expected: FAIL (`log_json` has no `from_used`; selection not wired).

- [ ] **Step 3: Extend `log_json`**

In `smtpbench/cli.py`, add two params to `log_json` (after `body_source=None,` at line 238):

```python
    from_used=None,
    journal_used=None,
```

and add to the `entry` dict (after `"body_source": body_source,` at line 256):

```python
        "from_used": from_used,
        "journal_used": journal_used,
```

- [ ] **Step 4: Wire selection into `send_email`**

Add the three globals to `send_email`'s `global` declaration (line 839):

```python
    global success_count, fail_count, retry_count, stop_requested, journal_enabled, journal_address
    global recipient_list, from_list, journal_list
```

(Python allows one `global` statement listing all, or two lines; keep ruff happy — a single line is fine but long, so two lines as shown.)

After `body_source = (...)` (ends ~line 849) and before `msg = create_message(...)`, insert:

```python
    eff_recipient = recipient_list.select(rng) if recipient_list else recipient
    eff_from = from_list.select(rng) if from_list else from_address
    eff_journal = (
        journal_list.select(rng)
        if (journal_enabled and journal_list)
        else journal_address
    )
```

Change the `create_message` call (line 850-852) to use the effective values:

```python
    msg = create_message(
        eff_recipient, eff_from, thread_id, message_id, attachment_configs, body_prefix
    )
```

Change the recipients assembly (lines 855-857):

```python
    recipients = [eff_recipient]
    if journal_enabled and eff_journal:
        recipients.append(eff_journal)
```

Change the envelope-from passed to `try_send_to_mx_hosts` (line 914) from `from_address` to `eff_from`:

```python
        mx_host_used, error = try_send_to_mx_hosts(
            eff_from, recipients, msg, port, tls_mode, transaction_timeout
        )
```

Add `from_used=eff_from, journal_used=(eff_journal if journal_enabled else None)` to **all four** `log_json(...)` calls in `send_email` (the two in the offline branch at ~872 and ~894, and the success/fail/retry calls in the online branch). Each call already passes `recipients=recipients, attachments=attachments, body_source=body_source`; append the two new kwargs alongside.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_smtpbench.py::TestLogJsonAddressFields tests/test_smtpbench.py::TestAddressSelectionInSend -v`
Expected: PASS.

- [ ] **Step 6: Run the full unit suite**

Run: `.venv/bin/python -m pytest -v -m "not integration"`
Expected: PASS (no regressions — existing `send_email`/`log_json` tests still green).

- [ ] **Step 7: Commit**

```bash
git add smtpbench/cli.py tests/test_smtpbench.py
git commit -m "feat: per-message address selection in send_email + log fields"
```

---

## Task 7: Summary block + startup INFO lines

**Files:**
- Modify: `smtpbench/cli.py` — `main()` summary_config (~line 1270-1279) and startup INFO output (~line 1202-1220)
- Test: `tests/test_smtpbench.py` (new class `TestSummaryAddressLists`)

**Interfaces:**
- Consumes: the three globals (Task 4).
- Produces: an `address_lists_summary()` helper returning the metadata-only dict `{"recipient": {...}|None, "from": ..., "journal": ...}` where each present entry is `{"file": <path>, "count": <int>, "order": <str>}`. Added under `summary_config["address_lists"]`.

Note: `AddressList` needs to remember its source path for the summary. Add a `source` attribute.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_smtpbench.py`:

```python
class TestSummaryAddressLists:
    def test_address_lists_summary_reports_metadata_only(self):
        from smtpbench import cli
        from smtpbench.cli import AddressList, address_lists_summary

        cli.recipient_list = AddressList(["a@x.com", "b@x.com"], "roundrobin")
        cli.recipient_list.source = "recipients.txt"
        cli.from_list = AddressList(["s@x.com"], "random")
        cli.from_list.source = "senders.txt"
        cli.journal_list = None

        summary = address_lists_summary()
        assert summary["recipient"] == {
            "file": "recipients.txt", "count": 2, "order": "roundrobin"
        }
        assert summary["from"] == {"file": "senders.txt", "count": 1, "order": "random"}
        assert summary["journal"] is None
        # No raw addresses leaked.
        assert "a@x.com" not in json.dumps(summary)
```

(`json` is imported at the top of the test file; if not, add `import json` inside the test.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_smtpbench.py::TestSummaryAddressLists -v`
Expected: FAIL (`address_lists_summary` undefined; `AddressList` has no `source`).

- [ ] **Step 3: Add `source` to `AddressList` and set it in the builder**

In `AddressList.__init__` (Task 1), add a `source` attribute defaulting to `None`:

```python
    def __init__(self, addresses, order, source=None):
        self.addresses = addresses
        self.order = order
        self.source = source
        self._idx = 0
        self._lock = threading.Lock()
```

In `build_address_list` (Task 3), pass the path:

```python
    return AddressList(addresses, order, source=path)
```

- [ ] **Step 4: Implement `address_lists_summary`**

In `smtpbench/cli.py`, near `write_summary`:

```python
def address_lists_summary():
    """Metadata-only summary of active address lists (never the addresses)."""
    def _entry(plan):
        if plan is None:
            return None
        return {"file": plan.source, "count": len(plan.addresses), "order": plan.order}

    return {
        "recipient": _entry(recipient_list),
        "from": _entry(from_list),
        "journal": _entry(journal_list),
    }
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_smtpbench.py::TestSummaryAddressLists -v`
Expected: PASS.

- [ ] **Step 6: Wire into `main()` summary + startup INFO**

Add to the `summary_config` dict (after `"body_text_dir": body_plan is not None,` at line 1278):

```python
        "address_lists": address_lists_summary(),
```

After the journal INFO line (`cli.py:1202-1203`), add startup INFO lines:

```python
    for label, plan in (
        ("Recipient", recipient_list),
        ("From", from_list),
        ("Journal", journal_list),
    ):
        if plan is not None:
            order_label = "round-robin" if plan.order == "roundrobin" else "random"
            print(
                f"[INFO] {label} list: {plan.source} "
                f"({len(plan.addresses)} addresses, {order_label})"
            )
```

- [ ] **Step 7: Run the full unit suite + lint**

Run:
```bash
.venv/bin/python -m pytest -v -m "not integration"
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```
Expected: tests PASS; ruff clean. If `ruff format --check` reports diffs, run `.venv/bin/ruff format .` and re-stage.

- [ ] **Step 8: Commit**

```bash
git add smtpbench/cli.py tests/test_smtpbench.py
git commit -m "feat: address_lists summary block + startup INFO lines"
```

---

## Task 8: Docs — help text, usage string, README, CHANGELOG

**Files:**
- Modify: `smtpbench/cli.py` `show_help` (the help string, ~line 86-155) and `__main__` usage string (line 1287-1295)
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Update `show_help`**

In the help string in `cli.py` (the `PARAMETERS`/options section around lines 86-155, near the `recipient`/`from_address`/`journal_address` entries), add six lines mirroring the existing `{Fore.YELLOW}key{Style.RESET_ALL}=...` format:

```
    {Fore.YELLOW}recipient_file{Style.RESET_ALL}=PATH     File of recipient addresses (needs lb_host= or eml_out_dir=)
    {Fore.YELLOW}from_file{Style.RESET_ALL}=PATH          File of From addresses
    {Fore.YELLOW}journal_file{Style.RESET_ALL}=PATH       File of journal addresses (needs journal=true)
    {Fore.YELLOW}recipient_file_order{Style.RESET_ALL}=random|roundrobin   Recipient selection (default random)
    {Fore.YELLOW}from_file_order{Style.RESET_ALL}=random|roundrobin        From selection (default random)
    {Fore.YELLOW}journal_file_order{Style.RESET_ALL}=random|roundrobin     Journal selection (default random)
```

Place them near the related single-value keys. Match the existing column alignment as closely as the surrounding lines.

- [ ] **Step 2: Update the `__main__` usage string**

In `cli.py:1287-1295`, append to the bracketed options (before the closing `"`):

```
            "[recipient_file=<path>] [from_file=<path>] [journal_file=<path>] "
            "[recipient_file_order=random|roundrobin] "
            "[from_file_order=random|roundrobin] [journal_file_order=random|roundrobin]"
```

Ensure the preceding line's trailing text still ends with a space so the concatenation is well-formed.

- [ ] **Step 3: Update README**

Add a subsection titled **"Address lists from a file"** near the recipient/from/journal documentation. Include:

- The six keys and what each does (table or list).
- The rule: `recipient_file` requires `lb_host=` (fixed relay) **or** `eml_out_dir=` (offline).
- `journal_file` requires `journal=true`.
- `*_file` overrides and cannot be combined with its single-value sibling.
- File format: one address per line; blank lines and `#` comments ignored; every address validated (exactly one `@`).
- Random vs round-robin (default random; round-robin gives even coverage across the run).
- A worked example, e.g.:

````markdown
```bash
smtpbench recipient_file=recipients.txt recipient_file_order=roundrobin \
          from_file=senders.txt \
          lb_host=smtp.example.com port=587 threads=5 messages=100
```
````

- A note that per-domain MX resolution for multi-domain recipient files is not supported yet (recipients go through the one relay); it may be added later but is slower and not benchmarking-relevant.

- [ ] **Step 4: Update CHANGELOG**

In the unreleased `## [1.2.0]` **Added** section of `CHANGELOG.md`, add one entry:

```markdown
- **Address lists from a file**: `recipient_file=` / `from_file=` / `journal_file=` each read a one-address-per-line file (blank lines and `#` comments ignored, every address validated) and select per message, independently. `*_file_order=random|roundrobin` (default `random`) is set per field. A `*_file` overrides and cannot be combined with its single-value counterpart. `recipient_file` requires `lb_host=` or `eml_out_dir=` (offline); `journal_file` requires `journal=true`. Chosen `from`/`journal` addresses are logged per message; the summary records file/count/order metadata only.
```

- [ ] **Step 5: Verify docs render / lint clean**

Run:
```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m pytest -v -m "not integration"
```
Expected: all clean/PASS. Manually eyeball `smtpbench --help` output:
```bash
.venv/bin/python -m smtpbench --help
```
Expected: the six new keys appear, aligned.

- [ ] **Step 6: Commit**

```bash
git add smtpbench/cli.py README.md CHANGELOG.md
git commit -m "docs: document address-list files (help, usage, README, changelog)"
```

---

## Task 9: Integration test

**Files:**
- Modify: `tests/test_smtpbench.py` (add an `@pytest.mark.integration` test, following the existing integration-test pattern in that file / `tests/run_integration_test.sh`)

**Interfaces:**
- Consumes: the full CLI end-to-end via the Docker Postfix server; existing integration helpers (mbox validation scoped by run UUID).

- [ ] **Step 1: Read the existing integration test(s)**

Run: `.venv/bin/python -m pytest -m integration --collect-only -q`
and read the existing integration test body in `tests/test_smtpbench.py` to reuse its Docker setup, run-UUID scoping, and mbox validation helpers. Match that structure exactly (do not invent a new harness).

- [ ] **Step 2: Write the integration test**

Add a test (mirroring the existing integration test's fixtures/teardown) that:
- Writes a temp `recipients.txt` with 3 valid addresses and a `senders.txt` with 2.
- Invokes the CLI (same mechanism the existing integration test uses) with `recipient_file=recipients.txt recipient_file_order=roundrobin from_file=senders.txt lb_host=<test server> port=<test port> threads=2 messages=6` plus whatever auth/TLS the existing test uses against the Docker server.
- After the run, validates (scoped to the current run UUID) that messages landed in the mbox and that the observed `From:` headers include more than one distinct sender (proving `from_file` rotation) and the recipients cover the file.

Because the exact Docker invocation and mbox-parsing helpers are defined by the existing integration test, reuse those symbols rather than duplicating them. If the existing test drives the CLI via `subprocess`, do the same; if via `main()` with patched argv, match that.

- [ ] **Step 3: Run the integration test (requires Docker)**

Run: `.venv/bin/python -m pytest -v -m integration -k address`
Expected: PASS (Docker Postfix spins up; messages validated for the run UUID).

If Docker is unavailable in this environment, note that and defer running to CI; do **not** mark the task complete on an unrun test — leave Step 3 unchecked and flag it.

- [ ] **Step 4: Commit**

```bash
git add tests/test_smtpbench.py
git commit -m "test: integration coverage for recipient_file/from_file rotation"
```

---

## Final verification

- [ ] **Full unit suite:** `.venv/bin/python -m pytest -v -m "not integration"` — all PASS.
- [ ] **Lint + format:** `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .` — clean.
- [ ] **Integration (if Docker available):** `.venv/bin/python -m pytest -v -m integration` — all PASS.
- [ ] **Version unchanged:** confirm `pyproject.toml` and `smtpbench/__init__.py` still read `1.2.0`.
- [ ] **Help renders:** `.venv/bin/python -m smtpbench --help` shows the six new keys.

# SMTPBench — Address Lists From a File — Design

**Date:** 2026-08-08
**Status:** Approved (pending written-spec review)
**Target release:** folded into the unreleased 1.2.0 (no version bump)

## Motivation

SMTPBench sends every message to a single `recipient`, from a single
`from_address`, with an optional single `journal_address`. Real load tests want
variety: spray a relay across hundreds of recipients, rotate sender identities,
and copy a journal mailbox — independently.

This feature adds the ability to draw each of those three fields from its own
address-list file, in any combination, unrelated to one another. Any subset of
the three files may be used at once; a field with no file falls back to its
existing single-value argument.

## Scope

In scope:

| Capability | CLI surface |
| --- | --- |
| Recipient (To) address list | `recipient_file=PATH` |
| From address list | `from_file=PATH` |
| Journal address list | `journal_file=PATH` |
| Per-field selection mode | `recipient_file_order=` / `from_file_order=` / `journal_file_order=` (`random` \| `roundrobin`, default `random`) |

Out of scope (documented as possible future work):

- **Per-domain MX resolution for a multi-domain recipient file.** For now a
  recipient file requires a fixed relay (`lb_host=`) or offline output
  (`eml_out_dir=`); all recipients are sent through the one target. Resolving
  MX per recipient domain would be slower and does not aid benchmarking, so it
  is deferred. If demand appears, it can be added behind an explicit opt-in.
- Weighted / probability-based address selection.
- Per-address templating of message content.

## CLI surface

Six new optional keys, all `key=value` (consistent with the existing parser):

| Key | Meaning | Default |
| --- | --- | --- |
| `recipient_file=PATH` | File of recipient (To) addresses | — |
| `from_file=PATH` | File of From addresses | — |
| `journal_file=PATH` | File of journal-copy addresses | — |
| `recipient_file_order=random\|roundrobin` | Selection mode for recipients | `random` |
| `from_file_order=random\|roundrobin` | Selection mode for From | `random` |
| `journal_file_order=random\|roundrobin` | Selection mode for journal | `random` |

### Coexistence and requirement rules

- A `*_file` key **overrides** its single-value sibling, and supplying **both**
  is a startup error:
  - `recipient_file=` + `recipient=` → error
  - `from_file=` + `from_address=` → error
  - `journal_file=` + `journal_address=` → error
- `recipient=` remains **required unless** `recipient_file=` is given — exactly
  one of the two must be present.
- `recipient_file=` **requires a single send target**: either `lb_host=` (fixed
  relay, DNS skipped) **or** `eml_out_dir=` (offline file output, no relay/DNS).
  Neither present → startup error, because there is no single domain from which
  to resolve MX. (Today `mx_hosts` is resolved once in `main()` from the single
  recipient's domain; a multi-domain file has no such single domain.)
- `journal_file=` takes effect only when `journal=true` (same gating as
  `journal_address` today). Supplying `journal_file=` without `journal=true` is
  a startup error, so a typo is never silently ignored.
- An `*_file_order=` key with no matching `*_file=` is a startup error.

## Architecture

The application remains single-file (`smtpbench/cli.py`) with the established
module-global-state-under-lock threading model. This feature follows the
existing plan-object idiom used by `BodyPlan`/`build_body_plan` and
`AttachmentPlan`/`build_attachment_plan`: parse once at startup into an object,
select per message via the already-seeded per-message RNG.

### Component: `AddressList`

A single field-agnostic class, placed next to `BodyPlan` in `cli.py`:

```python
class AddressList:
    """Per-message address selection from a parsed list of addresses.

    order="random":     rng.choice per message (reproducible per message,
                        given the fixed run_uuid:thread:message seed).
    order="roundrobin": cycle the list evenly across the whole run. The shared
                        index is guarded by a per-instance lock, so the three
                        fields' round-robin counters are fully independent.
    """

    def __init__(self, addresses, order):
        self.addresses = addresses          # non-empty list[str]
        self.order = order                  # "random" | "roundrobin"
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

The per-instance lock is deliberate: it is what makes the three fields'
round-robin cursors independent of one another (the design intent that the
fields are "unrelated to each other"), and it avoids contending on the global
`lock`.

### Component: `parse_address_file`

```python
def parse_address_file(path, field_label):
    """Read one address per line. Strip whitespace; skip blank lines and lines
    beginning with '#'. Validate every remaining address with the existing
    recipient rule (exactly one '@'). Fail-fast:
      - missing / unreadable file            -> raise
      - no valid addresses after filtering   -> raise
      - any address with != 1 '@'            -> raise, naming file+line+value
    Returns a non-empty list[str]."""
```

The multi-`@` check reuses the exact invariant `recipient` enforces today
(reject `value.count("@") != 1`), applied uniformly to all three fields.

### Component: `build_address_list`

```python
def build_address_list(args, field):
    """field in {'recipient', 'from', 'journal'}.
    Returns an AddressList, or None if the field's *_file key is absent.
    Reads '<field>_file' and '<field>_file_order' (default 'random'; validate
    the value is 'random' or 'roundrobin'); delegates parsing to
    parse_address_file."""
```

### Module globals

Three globals hold the built instances, built once in `main()`:

```python
recipient_list = None   # AddressList or None
from_list = None        # AddressList or None
journal_list = None     # AddressList or None
```

They are added to `tests/conftest.py`'s autouse `reset_globals` fixture (both
the before-yield and after-yield blocks). No bare round-robin index globals are
introduced — each cursor lives inside its `AddressList` instance.

## Data flow (send path, per message)

Selection is consumed in `send_email()`, at the point where the seeded
per-message RNG already exists (today it seeds attachment and body selection):

```
send_email(port, recipient, from_address, ...):
  rng = random.Random(f"{run_uuid}:{thread_id}:{message_id}")   # existing
  attachment_configs = attachment_plan.select_for_message(rng) if attachment_plan else []
  body_choice        = body_plan.select(rng)          if body_plan else None

  # NEW — each field independent; falls back to the passed-in single value:
  eff_recipient = recipient_list.select(rng) if recipient_list else recipient
  eff_from      = from_list.select(rng)      if from_list      else from_address
  eff_journal   = (journal_list.select(rng)  if (journal_enabled and journal_list)
                                             else journal_address)

  msg = create_message(eff_recipient, eff_from, thread_id, message_id,
                       attachment_configs, body_prefix)
  recipients = [eff_recipient]
  if journal_enabled and eff_journal:
      recipients.append(eff_journal)
  # try_send_to_mx_hosts uses eff_from as the SMTP envelope-from
```

Notes:

- **`worker()` and `send_email()` keep their `recipient`/`from_address`
  parameters.** These are the fallback defaults when no list is set. The lists
  are read from module globals (exactly like `attachment_plan`/`body_plan`), so
  signatures are unchanged; `send_email` adds the three list globals to its
  `global` declaration for read access.
- **`eff_from` is both the message `From` header and the SMTP envelope-from**,
  matching per message (`from_address` already served both roles).
- **RNG draw order is fixed** (attachments → body → recipient → from → journal)
  so a run using only random-mode lists is fully reproducible from the run UUID.
  Round-robin fields do **not** draw from `rng` (they use the instance index),
  so mixing a round-robin field in never perturbs the random fields' sequence.
- **Offline mode (`eml_out_dir`) composes unchanged.** The `recipient_file`
  target requirement is satisfied by `eml_out_dir` (see rules above); offline
  writes `{sha256}.eml` files with the effective addresses as headers, no
  relay/DNS involved.
- **MX resolution and the pre-flight banner check are unchanged.** Because
  `recipient_file=` requires `lb_host=` (in live mode), `mx_hosts` is the single
  relay resolved from `lb_host` exactly as today, and `check_smtp_banner()` runs
  against it before threads start. The recipient file never drives DNS. In
  offline mode both are skipped, as they already are.

## Error handling (all fail-fast at startup)

| Condition | Result |
| --- | --- |
| `recipient_file=` + `recipient=` both set | error (mutually exclusive) |
| `from_file=` + `from_address=` both set | error |
| `journal_file=` + `journal_address=` both set | error |
| neither `recipient=` nor `recipient_file=` present | error (recipient required) |
| `recipient_file=` without `lb_host=` and not offline (`eml_out_dir=` unset) | error (no single MX target) |
| `journal_file=` without `journal=true` | error (would be silently ignored) |
| `*_file_order=` present without its matching `*_file=` | error |
| `*_file_order=` value not in `{random, roundrobin}` | error listing valid values |
| file missing / unreadable / empty (no valid addresses) | error |
| any address in a file has `!= 1` `@` | error naming file, line number, offending value |

All checks run before any worker thread starts, consistent with
`build_attachment_plan`/`build_body_plan` and the existing credential/rate
validation. Messages use the existing `Fore.RED ✗ …{Style.RESET_ALL}` style.

## Logging & summary

- **Per-message JSON logs** record all three chosen values. `recipient` already
  surfaces through the `recipients=` field (which includes the journal address
  when enabled). Two fields are added to the `log_json` calls in `send_email`:
  `from_used` (effective From) and `journal_used` (effective journal, or null).
  Addresses are not credentials, so no redaction applies; the attachment
  `content`-stripping discipline is untouched.
- **Summary JSON (`summary_*.json`)** gains an `address_lists` block under
  `config`, metadata only — never the address contents:

  ```json
  "address_lists": {
    "recipient": {"file": "recipients.txt", "count": 500, "order": "roundrobin"},
    "from":      {"file": "senders.txt",    "count": 10,  "order": "random"},
    "journal":   null
  }
  ```

  Each present field records its filename, address count, and order; an absent
  field is `null`. This is enough to interpret a run without dumping the list.
- **Terminal startup output** prints one INFO line per active list, e.g.
  `[INFO] Recipient list: recipients.txt (500 addresses, round-robin)`,
  mirroring the existing journal/attachment INFO lines.

## File format

- One address per line.
- Leading/trailing whitespace stripped.
- Blank lines ignored.
- Lines beginning with `#` ignored (comments).
- Every remaining address validated (exactly one `@`); any violation aborts the
  run at startup.
- A file with no valid addresses after filtering is an error.

Example:

```
# Primary recipients
alice@example.com
bob@example.com

carol@example.com
```

## Testing strategy

Unit (`pytest -m "not integration"`), new test classes in `test_smtpbench.py`:

- `parse_address_file`: one-per-line parsing; `#` comments and blank lines
  skipped; whitespace stripped; empty/missing/unreadable raises; multi-`@`
  address raises naming file+line+value.
- `AddressList.select`: random mode with a seeded RNG is deterministic and stays
  within the list; round-robin cycles evenly and wraps (`_idx % len`); two
  instances keep independent counters.
- `build_address_list`: returns `None` when the `*_file` key is absent; reads
  order; rejects an invalid order value.
- Validation matrix (`main()`-level): each mutually-exclusive pair errors;
  `recipient_file` without `lb_host`/offline errors; the offline waiver passes;
  `journal_file` without `journal=true` errors; orphan `*_file_order` errors.
- Determinism: with all three files in random mode, a fixed `run_uuid` +
  thread/message yields the same three picks (locks the RNG draw order).
- `conftest.py` `reset_globals` updated for `recipient_list`/`from_list`/
  `journal_list` (before and after yield).

Integration (`pytest -m integration`, Docker Postfix):

- A run with `recipient_file=` + `lb_host=` (round-robin) + `from_file=`
  delivers to the mbox, and messages for the current run UUID show varied From
  headers and recipient addresses.

## Documentation

- **README:** new "Address lists from a file" subsection — the six keys, the
  `lb_host`/offline requirement for `recipient_file`, the `journal=true` gating,
  random vs round-robin, the file format, and a worked example.
- **`show_help` + `__main__` usage string:** add the six keys.
- **`CHANGELOG.md`:** fold into the unreleased `## [1.2.0]` **Added** section —
  no version bump (1.2.0 is not yet on PyPI). `pyproject.toml` and
  `smtpbench/__init__.py` stay at 1.2.0.

## Backward compatibility

- All six parameters are optional; any existing command line runs unchanged.
- With no `*_file` keys, behavior is exactly as today (single recipient / from /
  journal), including MX resolution and the pre-flight banner check.
- Existing log fields and the summary schema are only added to, never changed;
  `from_used`/`journal_used` and the `config.address_lists` block are additive.

# c11-attribution-v1: reviewer's package (run 1, 2026-11-06 UTC)

What the reviewer judges, and how, is in [PROTOCOL.md](PROTOCOL.md) ("Reviewer rubric"). Everything needed to check
each credited line is below: the upstream change with line numbers (new-side numbers are the ones attribution
uses), each requirement and the tests it names, those tests' source at the frozen commit, which declared tests ran
each changed line (from the mission's per-test record), and what `repo-ai coverage ID --json` reported. Nothing has
to run. Raw records: [results/run-1.jsonl](results/run-1.jsonl) (paths shortened). This package states facts and
points at things worth a look; it gives no verdict.

## What ran

- repo-ai **0.12.8** from PyPI (`repo-ai-cli==0.12.8`, fresh Python 3.12 virtualenv); **$0, no model call**: each
  mission is `--agent replay` with the upstream fix as the explicit proposal.
- Project code only in podman containers (podman machine `applehv`, 7 CPUs, 2 GiB), through repo-ai's podman backend
  and journey-live-v1's native check. Images used as they were (nothing pulled or built); in each the project is not
  installed (`pip show` fails).
- Prep (native, in the container): every defect qualifies (frozen tests fail at the base, pass with the upstream
  fix), and every declared test ID was collected, with the expected outcomes (change tests fail then pass, control
  tests pass on both trees). No declaration was corrected.

| defect | mission ID | `do` exit | effective verdict | observed (passport) | image (digest) | per-test record |
|---|---|---|---|---|---|---|
| humanize | `c4668d3105fd2b03ddce8724` | 2 | INCONCLUSIVE (image freshness not checked) | PASS | `journey-humanize-deps:1` `sha256:fae33dbc6969b42a39eccb37e2aaa0b19a1c2ad0505d500b20c94668cffa6b0b` | measured, complete, sys.monitoring, Python 3.12.16 |
| more-itertools | `c81c9c0a678d237f8069e8a4` | 2 | INCONCLUSIVE (same) | PASS | `journey-more-itertools-deps:1` `sha256:6d8437fa245cd3524c9cfb4c3edcb81ecd7eee78344d51f4886cabc61c313ade` | measured, complete, sys.monitoring, Python 3.12.16 |
| pyjwt | `c748c00c9330b7043acb3932` | 2 | INCONCLUSIVE (same) | PASS, standing PASS_WITH_PRE_EXISTING_FAILURES (`--expect-fix`; `test_get_jwt_set_sslcontext_default` needs the network) | `journey-pyjwt-deps:1` `sha256:832ca64b448ae84f01dbd1e8f680097181a92a4e2d3300d7d314efd9aff671eb` | measured, complete, sys.monitoring, Python 3.12.16 (tracer run exit 1: the pre-existing failure) |
| marshmallow | `320512624656e38fd1e2a86e` | 2 | INCONCLUSIVE | INCONCLUSIVE: baseline and candidate test IDs differ (`test_invalid_datetime_deserialization[07:14:40 2026-11-06]` vs `[07:14:42 …]`, a clock parameter) | `journey-marshmallow-deps:1` `sha256:e47ae5caa54417bf065cb2baa90416436a924a242313456856cc2a57bda4c854` | **not measured**: the measurement runs only after a PASS |

In the three measured missions the change-exercise run used the podman backend and the image pinned to the digest the
verified run recorded (`exercise.container.image_digest` equals the candidate executor's digest). `coverage`'s
headline is INCONCLUSIVE for all four and every row is `UNVERIFIED_INCONCLUSIVE` with the observation kept in
`observed_status`, as predeclared (a container mission's freshness reads `not checked`). Each mission took 8 to
37 seconds; no repo-ai workspace or `repo-ai-*` container was left behind.

## What this package can and cannot show

- **Attribution records exist for 3 real projects** (humanize, more-itertools, pyjwt): 14 changed executable lines,
  12 requirements. marshmallow produced none.
- **Shared-fixture crediting is not exercised.** None of the four suites has a session-, package-, module- or
  class-scoped fixture that runs project code (predeclared). The only function-scoped fixture that runs changed code
  is marshmallow's `serialized_user` (R3), and marshmallow was not measured. So the records contain **no fixture-scope
  evidence at all**; pyjwt's `jwt` fixture is function-scoped and runs no changed line.
- **Import-time attribution is not exercised either**: `run_outside_any_test` is empty in all three records (the
  changed lines are inside function bodies); the import-time case was marshmallow's `_get_fields`.
- **No node project and no host run** (protocol): per-file `node --test` attribution on a real project and host-run
  attribution stay unreviewed.
- In all three measured records, no test other than the declared ones ran a changed line
  (`run_by_tests_of_no_requirement` is empty), so the "undeclared tests" path shows nothing here either.
## humanize

### Upstream change, declaration and tests

```diff
diff --git a/src/humanize/filesize.py b/src/humanize/filesize.py
index 5650d02..30ba135 100644
--- a/src/humanize/filesize.py
+++ b/src/humanize/filesize.py
@@ -91,7 +91,7 @@ def naturalsize(
   91    91      abs_bytes = abs(bytes_)
   92    92  
   93    93      if abs_bytes == 1 and not gnu:
   94       -        return f"{bytes_} Byte"
         94 +        return f"{int(bytes_)} Byte"
   95    95  
   96    96      if abs_bytes < base:
   97    97          return f"{int(bytes_)}B" if gnu else f"{int(bytes_)} Bytes"
```

- **R1** (change): naturalsize accepts a float equal to 1 (1.0) and returns "1 Byte", as it does for the int 1 (upstream #250: regression for float)
  - `tests/test_filesize.py::test_naturalsize[test_args58-1 Byte]`
- **R2** (change): naturalsize accepts a numeric string equal to 1 ("1") and returns "1 Byte" (upstream #250: regression for str)
  - `tests/test_filesize.py::test_naturalsize[test_args59-1 Byte]`
- **R3** (preserve): control (case next to the changed ones): naturalsize(1) still returns "1 Byte"
  - `tests/test_filesize.py::test_naturalsize[test_args57-1 Byte]`
- **R4** (preserve): control (cases next to the changed ones): sizes other than 1 keep their format: 1024 in GNU form is "1.0K", 3141592 with "%.2f" is "3.14 MB"
  - `tests/test_filesize.py::test_naturalsize[test_args56-1.0K]`
  - `tests/test_filesize.py::test_naturalsize[test_args60-3.14 MB]`

`tests/test_filesize.py::test_naturalsize[test_args56-1.0K]`, `tests/test_filesize.py::test_naturalsize[test_args57-1 Byte]`, `tests/test_filesize.py::test_naturalsize[test_args58-1 Byte]`, `tests/test_filesize.py::test_naturalsize[test_args59-1 Byte]`, `tests/test_filesize.py::test_naturalsize[test_args60-3.14 MB]` at the frozen commit:

```python
   86  def test_naturalsize(test_args: list[int] | list[int | bool], expected: str) -> None:
   87      assert humanize.naturalsize(*test_args) == expected
   88  
   89      # Retest with negative input
   90      if isinstance(test_args[0], int):
   91          test_args[0] *= -1
   92      else:
   93          test_args[0] = f"-{test_args[0]}"
   94  
   95      assert humanize.naturalsize(*test_args) == "-" + expected
```

| changed line | declared tests that ran it | other tests that ran it | outside any test |
|---|---|---|---|
| `src/humanize/filesize.py:94` | `tests/test_filesize.py::test_naturalsize[test_args57-1 Byte]`, `tests/test_filesize.py::test_naturalsize[test_args58-1 Byte]`, `tests/test_filesize.py::test_naturalsize[test_args59-1 Byte]` | 0 |  |

### Attribution

headline `INCONCLUSIVE`, declaration `FROZEN_WITH_MISSION`, coverage exit 2; changed_code `{"assurance": "FULL", "changed_lines": 1, "unexercised": [], "unexercised_count": 0}`

| R | kind | status (observed) | changed_lines_run | count | unavailable |
|---|---|---|---|---|---|
| R1 | change | UNVERIFIED_INCONCLUSIVE (VERIFIED_FAIL_TO_PASS) | `src/humanize/filesize.py:94` | 1 |  |
| R2 | change | UNVERIFIED_INCONCLUSIVE (VERIFIED_FAIL_TO_PASS) | `src/humanize/filesize.py:94` | 1 |  |
| R3 | preserve | UNVERIFIED_INCONCLUSIVE (VERIFIED_PRESERVED) | `src/humanize/filesize.py:94` | 1 |  |
| R4 | preserve | UNVERIFIED_INCONCLUSIVE (VERIFIED_PRESERVED) | — | 0 |  |

`changed_lines_by_requirement` (note omitted): `{"changed_lines": 1, "complete": true, "granularity": "test", "measured": true, "run_by_tests_of_no_requirement": [], "run_by_tests_of_no_requirement_count": 0, "run_outside_any_test": []}`

Change-exercise record (mission state; `per_test` shown in the line table above): `{"assurance": "FULL", "changed_lines": 1, "unexercised": [], "backend": "podman", "container": {"image": "localhost/journey-humanize-deps:1@sha256:fae33dbc6969b42a39eccb37e2aaa0b19a1c2ad0505d500b20c94668cffa6b0b", "image_digest": "sha256:fae33dbc6969b42a39eccb37e2aaa0b19a1c2ad0505d500b20c94668cffa6b0b"}, "tracer": {"line_events": "sys.monitoring", "python": "3.12.16"}, "exit_code": 0, "per_test_complete": true, "per_test_granularity": "test", "changed_outside_tests": []}`

### Notes

Excerpt of the parametrize list (`tests/test_filesize.py` at the frozen commit; case 0 is line 14, so line 70 is
case 56):

```python
   70          ([1024, False, True], "1.0K"),
   71          ([1, False, False], "1 Byte"),
   72          ([1.0, False, False], "1 Byte"),
   73          (["1", False, False], "1 Byte"),
   74          ([3141592, False, False, "%.2f"], "3.14 MB"),
```

Facts for the reviewer:
- Line 94 is the only changed executable line. It is credited to R1 (case 58), R2 (case 59) and R3 (case 57), not to
  R4 (cases 56 and 60).
- The test body calls `naturalsize` twice per case (the second time negated: `-1`, `"-1.0"`, `"-1"`); both calls
  happen inside the same test, so either one entering line 94 credits the case.
- No undeclared test ran line 94; `naturalsize` is called in no other test file.

## more-itertools

### Upstream change, declaration and tests

```diff
diff --git a/more_itertools/more.py b/more_itertools/more.py
index 2fdd949..8bc6706 100755
--- a/more_itertools/more.py
+++ b/more_itertools/more.py
@@ -4273,22 +4273,23 @@ def unique_in_window(iterable, n, key=None):
 4273  4273          raise ValueError('n must be greater than 0')
 4274  4274  
 4275  4275      window = deque(maxlen=n)
 4276       -    uniques = set()
       4276 +    counts = defaultdict(int)
 4277  4277      use_key = key is not None
 4278  4278  
 4279  4279      for item in iterable:
 4280       -        k = key(item) if use_key else item
 4281       -        if k in uniques:
 4282       -            continue
 4283       -
 4284       -        if len(uniques) == n:
 4285       -            uniques.discard(window[0])
       4280 +        if len(window) == n:
       4281 +            to_discard = window[0]
       4282 +            if counts[to_discard] == 1:
       4283 +                del counts[to_discard]
       4284 +            else:
       4285 +                counts[to_discard] -= 1
 4286  4286  
 4287       -        uniques.add(k)
       4287 +        k = key(item) if use_key else item
       4288 +        if k not in counts:
       4289 +            yield item
       4290 +        counts[k] += 1
 4288  4291          window.append(k)
 4289  4292  
 4290       -        yield item
 4291       -
 4292  4293  
 4293  4294  def duplicates_everseen(iterable, key=None):
 4294  4295      """Yield duplicate elements after their first appearance.
```

- **R1** (change): unique_in_window with n=1 yields an item again once its earlier copy has left the window: [1, 2, 3, 4, 4, 4] with n=1 gives [1, 2, 3, 4, 4, 4] (upstream #720)
  - `tests/test_more.py::UniqueInWindowTests::test_basic`
- **R2** (change): unique_in_window counts repeated items in the window, so an item is yielded again only once every copy has left it: [0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 2, 3, 4, 2] with n=2 gives [0, 1, 0, 2, 3, 4, 2] (upstream #720)
  - `tests/test_more.py::UniqueInWindowTests::test_basic`
- **R3** (preserve): control (other test of the class the changed test is in): the key function decides uniqueness: [0, 1, 3, 4, 5, 6, 7, 8, 9] with n=3 and key x // 3 gives [0, 3, 6, 9]
  - `tests/test_more.py::UniqueInWindowTests::test_key`
- **R4** (preserve): control (other test of the class the changed test is in): n <= 0 raises ValueError
  - `tests/test_more.py::UniqueInWindowTests::test_invalid_n`

`tests/test_more.py::UniqueInWindowTests::test_basic` at the frozen commit:

```python
 4874      def test_basic(self):
 4875          for iterable, n, expected in [
 4876              (range(9), 10, list(range(9))),
 4877              (range(20), 10, list(range(20))),
 4878              ([1, 2, 3, 4, 4, 4], 1, [1, 2, 3, 4, 4, 4]),
 4879              ([1, 2, 3, 4, 4, 4], 2, [1, 2, 3, 4]),
 4880              ([1, 2, 3, 4, 4, 4], 3, [1, 2, 3, 4]),
 4881              ([1, 2, 3, 4, 4, 4], 4, [1, 2, 3, 4]),
 4882              ([1, 2, 3, 4, 4, 4], 5, [1, 2, 3, 4]),
 4883              (
 4884                  [0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 2, 3, 4, 2],
 4885                  2,
 4886                  [0, 1, 0, 2, 3, 4, 2],
 4887              ),
 4888          ]:
 4889              with self.subTest(expected=expected):
 4890                  actual = list(mi.unique_in_window(iterable, n))
 4891                  self.assertEqual(actual, expected)
```

`tests/test_more.py::UniqueInWindowTests::test_invalid_n` at the frozen commit:

```python
 4870      def test_invalid_n(self):
 4871          with self.assertRaises(ValueError):
 4872              list(mi.unique_in_window([], 0))
```

`tests/test_more.py::UniqueInWindowTests::test_key` at the frozen commit:

```python
 4893      def test_key(self):
 4894          iterable = [0, 1, 3, 4, 5, 6, 7, 8, 9]
 4895          n = 3
 4896          key = lambda x: x // 3
 4897          actual = list(mi.unique_in_window(iterable, n, key=key))
 4898          expected = [0, 3, 6, 9]
 4899          self.assertEqual(actual, expected)
```

| changed line | declared tests that ran it | other tests that ran it | outside any test |
|---|---|---|---|
| `more_itertools/more.py:4276` | `tests/test_more.py::UniqueInWindowTests::test_basic`, `tests/test_more.py::UniqueInWindowTests::test_key` | 0 |  |
| `more_itertools/more.py:4280` | `tests/test_more.py::UniqueInWindowTests::test_basic`, `tests/test_more.py::UniqueInWindowTests::test_key` | 0 |  |
| `more_itertools/more.py:4281` | `tests/test_more.py::UniqueInWindowTests::test_basic`, `tests/test_more.py::UniqueInWindowTests::test_key` | 0 |  |
| `more_itertools/more.py:4282` | `tests/test_more.py::UniqueInWindowTests::test_basic`, `tests/test_more.py::UniqueInWindowTests::test_key` | 0 |  |
| `more_itertools/more.py:4283` | `tests/test_more.py::UniqueInWindowTests::test_basic`, `tests/test_more.py::UniqueInWindowTests::test_key` | 0 |  |
| `more_itertools/more.py:4285` | `tests/test_more.py::UniqueInWindowTests::test_basic`, `tests/test_more.py::UniqueInWindowTests::test_key` | 0 |  |
| `more_itertools/more.py:4287` | `tests/test_more.py::UniqueInWindowTests::test_basic`, `tests/test_more.py::UniqueInWindowTests::test_key` | 0 |  |
| `more_itertools/more.py:4288` | `tests/test_more.py::UniqueInWindowTests::test_basic`, `tests/test_more.py::UniqueInWindowTests::test_key` | 0 |  |
| `more_itertools/more.py:4289` | `tests/test_more.py::UniqueInWindowTests::test_basic`, `tests/test_more.py::UniqueInWindowTests::test_key` | 0 |  |
| `more_itertools/more.py:4290` | `tests/test_more.py::UniqueInWindowTests::test_basic`, `tests/test_more.py::UniqueInWindowTests::test_key` | 0 |  |

### Attribution

headline `INCONCLUSIVE`, declaration `FROZEN_WITH_MISSION`, coverage exit 2; changed_code `{"assurance": "FULL", "changed_lines": 10, "unexercised": [], "unexercised_count": 0}`

| R | kind | status (observed) | changed_lines_run | count | unavailable |
|---|---|---|---|---|---|
| R1 | change | UNVERIFIED_INCONCLUSIVE (VERIFIED_FAIL_TO_PASS) | `more_itertools/more.py:4276`, `more_itertools/more.py:4280`, `more_itertools/more.py:4281`, `more_itertools/more.py:4282`, `more_itertools/more.py:4283`, `more_itertools/more.py:4285`, `more_itertools/more.py:4287`, `more_itertools/more.py:4288`, `more_itertools/more.py:4289`, `more_itertools/more.py:4290` | 10 |  |
| R2 | change | UNVERIFIED_INCONCLUSIVE (VERIFIED_FAIL_TO_PASS) | `more_itertools/more.py:4276`, `more_itertools/more.py:4280`, `more_itertools/more.py:4281`, `more_itertools/more.py:4282`, `more_itertools/more.py:4283`, `more_itertools/more.py:4285`, `more_itertools/more.py:4287`, `more_itertools/more.py:4288`, `more_itertools/more.py:4289`, `more_itertools/more.py:4290` | 10 |  |
| R3 | preserve | UNVERIFIED_INCONCLUSIVE (VERIFIED_PRESERVED) | `more_itertools/more.py:4276`, `more_itertools/more.py:4280`, `more_itertools/more.py:4281`, `more_itertools/more.py:4282`, `more_itertools/more.py:4283`, `more_itertools/more.py:4285`, `more_itertools/more.py:4287`, `more_itertools/more.py:4288`, `more_itertools/more.py:4289`, `more_itertools/more.py:4290` | 10 |  |
| R4 | preserve | UNVERIFIED_INCONCLUSIVE (VERIFIED_PRESERVED) | — | 0 |  |

`changed_lines_by_requirement` (note omitted): `{"changed_lines": 10, "complete": true, "granularity": "test", "measured": true, "run_by_tests_of_no_requirement": [], "run_by_tests_of_no_requirement_count": 0, "run_outside_any_test": []}`

`shared_tests`: `{"tests/test_more.py::UniqueInWindowTests::test_basic": ["unique_in_window with n=1 yields an item again once its earlier copy has left the window: [1, 2, 3, 4, 4, 4] with n=1 gives [1, 2, 3, 4, 4, 4] (upstream #720)", "unique_in_window counts repeated items in the window, so an item is yielded again only once every copy has left it: [0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 2, 3, 4, 2] with n=2 gives [0, 1, 0, 2, 3, 4, 2] (upstream #720)"]}`

Change-exercise record (mission state; `per_test` shown in the line table above): `{"assurance": "FULL", "changed_lines": 10, "unexercised": [], "backend": "podman", "container": {"image": "localhost/journey-more-itertools-deps:1@sha256:6d8437fa245cd3524c9cfb4c3edcb81ecd7eee78344d51f4886cabc61c313ade", "image_digest": "sha256:6d8437fa245cd3524c9cfb4c3edcb81ecd7eee78344d51f4886cabc61c313ade"}, "tracer": {"line_events": "sys.monitoring", "python": "3.12.16"}, "exit_code": 0, "per_test_complete": true, "per_test_granularity": "test", "changed_outside_tests": []}`

### Notes

Facts for the reviewer:
- R1 and R2 name the same test (`test_basic`, one test with `subTest` cases), so their credited sets are identical
  by construction; `shared_tests` flags it. Test-level granularity cannot separate subTest cases.
- R3's control test `test_key` is credited with all 10 changed lines, including both branches 4283 (`del`) and 4285
  (`-= 1`). Its keys (`x // 3` over `[0, 1, 3, 4, 5, 6, 7, 8, 9]`) are `0, 0, 1, 1, 1, 2, 2, 2, 3` with n = 3.
- R4's control test `test_invalid_n` (n = 0) is credited with nothing; the `ValueError` is raised at line 4273, inside
  the generator before line 4276.
- Line 4284 (`else:`) is not in the changed executable set (no line event for `else:`); the blank line 4286 is
  context, not added.
- Only `test_basic` and `test_key` ran changed lines. The docstring examples of `unique_in_window` are not collected
  (the project configures no `--doctest-modules`), and `unique_in_window` is called in no other test.

## pyjwt

### Upstream change, declaration and tests

```diff
diff --git a/jwt/api_jwt.py b/jwt/api_jwt.py
index fa4d5e6..3a20143 100644
--- a/jwt/api_jwt.py
+++ b/jwt/api_jwt.py
@@ -419,11 +419,11 @@ class PyJWT:
  419   419          if "iss" not in payload:
  420   420              raise MissingRequiredClaimError("iss")
  421   421  
  422       -        if isinstance(issuer, Sequence):
  423       -            if payload["iss"] not in issuer:
        422 +        if isinstance(issuer, str):
        423 +            if payload["iss"] != issuer:
  424   424                  raise InvalidIssuerError("Invalid issuer")
  425   425          else:
  426       -            if payload["iss"] != issuer:
        426 +            if payload["iss"] not in issuer:
  427   427                  raise InvalidIssuerError("Invalid issuer")
  428   428  
  429   429
```

- **R1** (change): decode with a str issuer rejects a token whose iss only partly matches it (iss "urn:" against issuer "urn:expected") with InvalidIssuerError: a str issuer is compared by equality, not with `in`
  - `tests/test_api_jwt.py::TestJWT::test_rasise_exception_on_partial_issuer_match`
- **R2** (preserve): control (commit message: a str issuer is compared by equality): a token whose iss equals the str issuer is accepted; a different iss raises InvalidIssuerError
  - `tests/test_api_jwt.py::TestJWT::test_check_issuer_when_valid`
  - `tests/test_api_jwt.py::TestJWT::test_raise_exception_invalid_issuer`
- **R3** (preserve): control (commit message: a list issuer is checked by membership): a token whose iss is one of the listed issuers is accepted; one not listed raises InvalidIssuerError
  - `tests/test_api_jwt.py::TestJWT::test_check_issuer_list_when_valid`
  - `tests/test_api_jwt.py::TestJWT::test_raise_exception_invalid_issuer_list`
- **R4** (preserve): control (test right before the changed one): with an issuer required, a token without iss raises MissingRequiredClaimError for "iss"
  - `tests/test_api_jwt.py::TestJWT::test_raise_exception_token_without_issuer`

`tests/test_api_jwt.py::TestJWT::test_check_issuer_list_when_valid` at the frozen commit:

```python
  501      def test_check_issuer_list_when_valid(self, jwt):
  502          issuer = ["urn:foo", "urn:bar"]
  503          payload = {"some": "payload", "iss": "urn:foo"}
  504          token = jwt.encode(payload, "secret")
  505          jwt.decode(token, "secret", issuer=issuer, algorithms=["HS256"])
```

`tests/test_api_jwt.py::TestJWT::test_check_issuer_when_valid` at the frozen commit:

```python
  495      def test_check_issuer_when_valid(self, jwt):
  496          issuer = "urn:foo"
  497          payload = {"some": "payload", "iss": "urn:foo"}
  498          token = jwt.encode(payload, "secret")
  499          jwt.decode(token, "secret", issuer=issuer, algorithms=["HS256"])
```

`tests/test_api_jwt.py::TestJWT::test_raise_exception_invalid_issuer` at the frozen commit:

```python
  507      def test_raise_exception_invalid_issuer(self, jwt):
  508          issuer = "urn:wrong"
  509  
  510          payload = {"some": "payload", "iss": "urn:foo"}
  511  
  512          token = jwt.encode(payload, "secret")
  513  
  514          with pytest.raises(InvalidIssuerError):
  515              jwt.decode(token, "secret", issuer=issuer, algorithms=["HS256"])
```

`tests/test_api_jwt.py::TestJWT::test_raise_exception_invalid_issuer_list` at the frozen commit:

```python
  517      def test_raise_exception_invalid_issuer_list(self, jwt):
  518          issuer = ["urn:wrong", "urn:bar", "urn:baz"]
  519  
  520          payload = {"some": "payload", "iss": "urn:foo"}
  521  
  522          token = jwt.encode(payload, "secret")
  523  
  524          with pytest.raises(InvalidIssuerError):
  525              jwt.decode(token, "secret", issuer=issuer, algorithms=["HS256"])
```

`tests/test_api_jwt.py::TestJWT::test_raise_exception_token_without_issuer` at the frozen commit:

```python
  455      def test_raise_exception_token_without_issuer(self, jwt):
  456          issuer = "urn:wrong"
  457  
  458          payload = {"some": "payload"}
  459  
  460          token = jwt.encode(payload, "secret")
  461  
  462          with pytest.raises(MissingRequiredClaimError) as exc:
  463              jwt.decode(token, "secret", issuer=issuer, algorithms=["HS256"])
  464  
  465          assert exc.value.claim == "iss"
```

`tests/test_api_jwt.py::TestJWT::test_rasise_exception_on_partial_issuer_match` at the frozen commit:

```python
  467      def test_rasise_exception_on_partial_issuer_match(self, jwt):
  468          issuer = "urn:expected"
  469  
  470          payload = {"iss": "urn:"}
  471  
  472          token = jwt.encode(payload, "secret")
  473  
  474          with pytest.raises(InvalidIssuerError):
  475              jwt.decode(token, "secret", issuer=issuer, algorithms=["HS256"])
```

| changed line | declared tests that ran it | other tests that ran it | outside any test |
|---|---|---|---|
| `jwt/api_jwt.py:422` | `tests/test_api_jwt.py::TestJWT::test_check_issuer_list_when_valid`, `tests/test_api_jwt.py::TestJWT::test_check_issuer_when_valid`, `tests/test_api_jwt.py::TestJWT::test_raise_exception_invalid_issuer`, `tests/test_api_jwt.py::TestJWT::test_raise_exception_invalid_issuer_list`, `tests/test_api_jwt.py::TestJWT::test_rasise_exception_on_partial_issuer_match` | 0 |  |
| `jwt/api_jwt.py:423` | `tests/test_api_jwt.py::TestJWT::test_check_issuer_when_valid`, `tests/test_api_jwt.py::TestJWT::test_raise_exception_invalid_issuer`, `tests/test_api_jwt.py::TestJWT::test_rasise_exception_on_partial_issuer_match` | 0 |  |
| `jwt/api_jwt.py:426` | `tests/test_api_jwt.py::TestJWT::test_check_issuer_list_when_valid`, `tests/test_api_jwt.py::TestJWT::test_raise_exception_invalid_issuer_list` | 0 |  |

### Attribution

headline `INCONCLUSIVE`, declaration `FROZEN_WITH_MISSION`, coverage exit 2; changed_code `{"assurance": "FULL", "changed_lines": 3, "unexercised": [], "unexercised_count": 0}`

| R | kind | status (observed) | changed_lines_run | count | unavailable |
|---|---|---|---|---|---|
| R1 | change | UNVERIFIED_INCONCLUSIVE (VERIFIED_FAIL_TO_PASS) | `jwt/api_jwt.py:422`, `jwt/api_jwt.py:423` | 2 |  |
| R2 | preserve | UNVERIFIED_INCONCLUSIVE (VERIFIED_PRESERVED) | `jwt/api_jwt.py:422`, `jwt/api_jwt.py:423` | 2 |  |
| R3 | preserve | UNVERIFIED_INCONCLUSIVE (VERIFIED_PRESERVED) | `jwt/api_jwt.py:422`, `jwt/api_jwt.py:426` | 2 |  |
| R4 | preserve | UNVERIFIED_INCONCLUSIVE (VERIFIED_PRESERVED) | — | 0 |  |

`changed_lines_by_requirement` (note omitted): `{"changed_lines": 3, "complete": true, "granularity": "test", "measured": true, "run_by_tests_of_no_requirement": [], "run_by_tests_of_no_requirement_count": 0, "run_outside_any_test": []}`

`other_obligations`: `["failures accepted as pre-existing in this scoped mission: tests/test_jwks_client.py::TestPyJWKClient::test_get_jwt_set_sslcontext_default"]`

Change-exercise record (mission state; `per_test` shown in the line table above): `{"assurance": "FULL", "changed_lines": 3, "unexercised": [], "backend": "podman", "container": {"image": "localhost/journey-pyjwt-deps:1@sha256:832ca64b448ae84f01dbd1e8f680097181a92a4e2d3300d7d314efd9aff671eb", "image_digest": "sha256:832ca64b448ae84f01dbd1e8f680097181a92a4e2d3300d7d314efd9aff671eb"}, "tracer": {"line_events": "sys.monitoring", "python": "3.12.16"}, "exit_code": 1, "per_test_complete": true, "per_test_granularity": "test", "changed_outside_tests": []}`

### Notes

Facts for the reviewer:
- Each declared test's `issuer` argument and the lines it was credited with: str issuer (`test_rasise_…partial…`,
  `test_check_issuer_when_valid`, `test_raise_exception_invalid_issuer`) → 422, 423; list issuer
  (`test_check_issuer_list_when_valid`, `test_raise_exception_invalid_issuer_list`) → 422, 426; no `iss` in the
  payload (`test_raise_exception_token_without_issuer`, R4) → nothing (it raises at line 420).
- `tests/test_api_jwt.py` has six `issuer=` calls, one in each declared test; no other test file mentions `issuer`.
  No undeclared test ran a changed line.
- All six tests take the function-scoped `jwt` fixture (`return PyJWT()`), which runs no changed line, so fixture
  attribution cannot be observed here.
- The tracer run's exit code is 1 (the network-dependent pre-existing failure) and the record is still marked
  complete: repo-ai counts exit 0 or 1 as a full run.

## marshmallow

### Upstream change, declaration and tests

```diff
diff --git a/src/marshmallow/schema.py b/src/marshmallow/schema.py
index 0298274e..f1ed1201 100644
--- a/src/marshmallow/schema.py
+++ b/src/marshmallow/schema.py
@@ -33,7 +33,6 @@ from marshmallow.utils import (
   33    33      RAISE,
   34    34      get_value,
   35    35      is_collection,
   36       -    is_instance_or_subclass,
   37    36      missing,
   38    37      set_value,
   39    38      validate_unknown_parameter_value,
@@ -45,11 +44,17 @@ def _get_fields(attrs) -> list[tuple[str, Field]]:
   45    44  
   46    45      :param attrs: Mapping of class attributes
   47    46      """
   48       -    return [
   49       -        (field_name, field_value)
   50       -        for field_name, field_value in attrs.items()
   51       -        if is_instance_or_subclass(field_value, ma_fields.Field)
   52       -    ]
         47 +    ret = []
         48 +    for field_name, field_value in attrs.items():
         49 +        if isinstance(field_value, type) and issubclass(field_value, ma_fields.Field):
         50 +            raise TypeError(
         51 +                f'Field for "{field_name}" must be declared as a '
         52 +                "Field instance, not a class. "
         53 +                f'Did you mean "fields.{field_value.__name__}()"?'
         54 +            )
         55 +        elif isinstance(field_value, ma_fields.Field):
         56 +            ret.append((field_name, field_value))
         57 +    return ret
   53    58  
   54    59  
   55    60  # This function allows Schemas to inherit from non-Schema classes and ensures
@@ -1050,20 +1055,7 @@ class Schema(metaclass=SchemaMeta):
 1050  1055              field_obj.load_only = True
 1051  1056          if field_name in self.dump_only:
 1052  1057              field_obj.dump_only = True
 1053       -        try:
 1054       -            field_obj._bind_to_schema(field_name, self)
 1055       -        except TypeError as error:
 1056       -            # Field declared as a class, not an instance. Ignore type checking because
 1057       -            # we handle unsupported arg types, i.e. this is dead code from
 1058       -            # the type checker's perspective.
 1059       -            if isinstance(field_obj, type) and issubclass(field_obj, ma_fields.Field):
 1060       -                msg = (
 1061       -                    f'Field for "{field_name}" must be declared as a '
 1062       -                    "Field instance, not a class. "
 1063       -                    f'Did you mean "fields.{field_obj.__name__}()"?'  # type: ignore
 1064       -                )
 1065       -                raise TypeError(msg) from error
 1066       -            raise error
       1058 +        field_obj._bind_to_schema(field_name, self)
 1067  1059          self.on_bind_field(field_name, field_obj)
 1068  1060  
 1069  1061      def _invoke_dump_processors(
diff --git a/src/marshmallow/utils.py b/src/marshmallow/utils.py
index 24ebd4f4..34fa517a 100644
--- a/src/marshmallow/utils.py
+++ b/src/marshmallow/utils.py
@@ -48,14 +48,6 @@ def is_collection(obj) -> bool:
   48    48      return is_iterable_but_not_string(obj) and not isinstance(obj, Mapping)
   49    49  
   50    50  
   51       -def is_instance_or_subclass(val, class_) -> bool:
   52       -    """Return True if ``val`` is either a subclass or instance of ``class_``."""
   53       -    try:
   54       -        return issubclass(val, class_)
   55       -    except TypeError:
   56       -        return isinstance(val, class_)
   57       -
   58       -
   59    51  # https://stackoverflow.com/a/27596917
   60    52  def is_aware(datetime: dt.datetime) -> bool:
   61    53      return (
```

- **R1** (change): A Schema subclass that declares a field as a class (name = fields.String) raises TypeError('Field for "name" must be declared as a Field instance ...') when the class is defined, not when it is used (upstream #2772)
  - `tests/test_schema.py::test_fields_must_be_declared_as_instances`
- **R2** (preserve): control (test right after the changed one, a regression test): a TypeError raised in on_bind_field propagates out of Schema() unchanged
  - `tests/test_schema.py::test_bind_field_does_not_swallow_typeerror`
- **R3** (preserve): control (test right before the changed one; its schema is built in the function-scoped serialized_user fixture): a Function field dumps what its function returns
  - `tests/test_schema.py::test_function_field`

`tests/test_schema.py::test_bind_field_does_not_swallow_typeerror` at the frozen commit:

```python
  549  def test_bind_field_does_not_swallow_typeerror():
  550      class MySchema(Schema):
  551          name = fields.Str()
  552  
  553          def on_bind_field(self, field_name, field_obj):
  554              raise TypeError("boom")
  555  
  556      with pytest.raises(TypeError, match="boom"):
  557          MySchema()
```

`tests/test_schema.py::test_fields_must_be_declared_as_instances` at the frozen commit:

```python
  539  def test_fields_must_be_declared_as_instances(user):
  540      with pytest.raises(
  541          TypeError, match='Field for "name" must be declared as a Field instance'
  542      ):
  543  
  544          class BadUserSchema(Schema):
  545              name = fields.String
```

`tests/test_schema.py::test_function_field` at the frozen commit:

```python
  535  def test_function_field(serialized_user, user):
  536      assert serialized_user["lowername"] == user.name.lower()
```

(No per-line table: no per-test record was made for this mission.)

### Attribution

headline `INCONCLUSIVE`, declaration `FROZEN_WITH_MISSION`, coverage exit 2; changed_code `{"assurance": "NOT_RECORDED"}`

| R | kind | status (observed) | changed_lines_run | count | unavailable |
|---|---|---|---|---|---|
| R1 | change | UNVERIFIED_INCONCLUSIVE (VERIFIED_FAIL_TO_PASS) | (not recorded) |  |  |
| R2 | preserve | UNVERIFIED_INCONCLUSIVE (VERIFIED_PRESERVED) | (not recorded) |  |  |
| R3 | preserve | UNVERIFIED_INCONCLUSIVE (VERIFIED_PRESERVED) | (not recorded) |  |  |

`changed_lines_by_requirement` (note omitted): `{"measured": false, "reason": "not measured (recorded for pytest and node --test missions run with a frozen --requirements declaration)"}`

`other_obligations`: `["whether the frozen tests ran the changed code was not measured for this mission"]`

Change-exercise record: none in the mission state (`exercise` absent).

### Notes

Facts for the reviewer:
- Nothing to check line by line: the mission was INCONCLUSIVE (test IDs carrying the wall-clock time differ between
  the baseline and candidate runs), the change-exercise measurement runs only after a PASS, so there is no
  `exercise` record and `changed_lines_by_requirement` is `measured: false`.
- The reason `coverage` gives is "not measured (recorded for pytest and node --test missions run with a frozen
  --requirements declaration)". This mission is a pytest mission with a frozen declaration; the actual cause (the
  verdict was not PASS) is not stated.
- The cases this defect would have exercised, kept here for a later study: `_get_fields` (new lines 47-57) runs when a
  Schema class is defined, so classes in `tests/base.py` and at module level of the test files run it at import (no
  test), and classes defined in a test body (R1, R2) run it in that test; line 1058 runs on `Schema()`; R3's
  `test_function_field` gets its schema built and dumped in the function-scoped `serialized_user` fixture
  (`tests/conftest.py` lines 25-27: `return UserSchema().dump(user)`).


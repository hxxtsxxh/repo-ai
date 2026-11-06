"""C11, Node per test file: reading V8 coverage output (untrusted) and mapping its UTF-16 offsets to lines."""
import json
import os
import shutil
import subprocess

import pytest
from repo_ai.mission import v8lines as v8

COV = '.repo-ai/run/cov'


def u16(text):
    return len(text.encode('utf-16-le')) // 2


def at(text, needle):
    """UTF-16 offset of `needle` in `text` (what V8 reports)."""
    return u16(text[:text.index(needle)])


def whole(text, *inner, count=1):
    """One script entry: the outermost range over the whole text, then `inner` (start, end, count) ranges."""
    return [(0, u16(text), count), *inner]


# -- offsets to lines ---------------------------------------------------------------------------------------------

def test_a_block_that_never_ran_inside_a_function_that_did_is_not_run():
    text = 'function f(a) {\n  if (a) {\n    return 1;\n  }\n  return 2;\n}\nf(0);\n'
    entry = whole(text, (at(text, 'function'), at(text, 'f(0)') - 1, 1),
                  (at(text, '{\n    return 1'), at(text, '  return 2'), 0))
    executable, ran = v8.line_status(text, [entry])
    assert executable == {1, 2, 3, 5, 7}
    assert ran == {1, 2, 5, 7}, 'line 3 is only in the count-0 block; line 2 opens it but its condition ran'


def test_nested_ranges_the_innermost_count_wins():
    text = 'const a = 1;\nconst b = 2;\nconst c = 3;\nconst d = 4;\n'
    # outer 1 > middle 0 (lines 2-4) > inner 5 (line 3)
    entry = whole(text, (at(text, 'const b'), u16(text), 0), (at(text, 'const c'), at(text, 'const d'), 5))
    assert v8.line_status(text, [entry])[1] == {1, 3}
    # the same ranges listed innermost first: order in the file must not matter
    reordered = [entry[0], entry[2], entry[1]]
    assert v8.line_status(text, [reordered])[1] == {1, 3}


def test_a_function_never_called_is_not_run_and_the_same_text_ran_in_another_process_is():
    text = 'exports.f = () => {\n  return 1;\n};\n'
    body = (at(text, '() =>'), at(text, '};') + 1, 0)
    assert v8.line_status(text, [whole(text, body)])[1] == {1}, 'the export assignment ran, the body did not'
    called = (at(text, '() =>'), at(text, '};') + 1, 1)
    assert v8.line_status(text, [whole(text, body), whole(text, called)])[1] == {1, 2}


def test_crlf_line_endings_count_each_cr_as_one_unit():
    text = 'const a = 1;\r\nfunction g() {\r\n  return 2;\r\n}\r\nconst z = 3;\r\n'
    entry = whole(text, (at(text, 'function g'), at(text, '}\r\nconst z') + 1, 0))
    executable, ran = v8.line_status(text, [entry])
    assert executable == {1, 2, 3, 5} and ran == {1, 5}


def test_non_ascii_before_the_offset_is_counted_in_utf16_units_not_bytes_or_code_points():
    # e-acute: 2 UTF-8 bytes, 1 UTF-16 unit; the emoji: 4 UTF-8 bytes, 1 code point, 2 UTF-16 units
    text = 'const s = "é\U0001F600\U0001F600";\nfunction g() {\n  return 1;\n}\nconst t = 2;\n'
    entry = whole(text, (at(text, 'function g'), at(text, '}\nconst t') + 1, 0))
    assert v8.line_status(text, [entry]) == ({1, 2, 3, 5}, {1, 5})
    # code-point offsets (2 too small) would put the count-0 block's start on line 1 and its end before line 4
    assert at(text, 'function g') == len(text[:text.index('function g')]) + 2


def test_a_range_covering_part_of_a_line_marks_it_run():
    text = 'let n = 0; if (x) { n = 1; }\nlater();\n'
    # the whole of line 1 except `n = 1;` and its block never ran ... but `let n = 0; if (x) ` did
    entry = whole(text, (at(text, '{ n = 1'), at(text, '\nlater'), 0))
    assert v8.line_status(text, [entry])[1] == {1, 2}
    # and a line all of whose code lies in a count-0 range did not run
    entry2 = whole(text, (0, at(text, '\nlater'), 0))
    assert v8.line_status(text, [entry2])[1] == {2}


def test_a_byte_order_mark_kept_by_commonjs_or_dropped_by_an_es_module_both_map_and_anything_else_is_refused():
    text = '﻿const a = 1;\nfunction g() {\n  return 2;\n}\n'
    cjs = whole(text, (at(text, 'function g'), u16(text) - 1, 0))
    assert v8.line_status(text, [cjs])[1] == {1}
    body = text[1:]
    esm = [(0, u16(body), 1), (at(body, 'function g'), u16(body) - 1, 0)]
    assert v8.line_status(text, [esm])[1] == {1}
    with pytest.raises(v8.Unavailable, match='does not match its text'):
        v8.line_status(text, [[(0, u16(text) + 7, 1)]])
    with pytest.raises(v8.Unavailable, match='does not match its text'):
        v8.line_status(body, [[(0, u16(body) - 1, 1)]])  # no mark to explain a missing unit


def test_executable_lines_skip_blank_comment_and_punctuation_only_lines():
    text = ('// a comment\n'                     # 1
            '/* a block\n'                       # 2
            '   comment without a star */\n'     # 3
            '\n'                                 # 4
            'const u = "http://x"; // tail\n'    # 5: a string holding // is code
            '});\n'                              # 6: punctuation only
            'const r = /\\/*$/;\n'               # 7: a regular expression holding /* is not a comment
            'const k = 1;\n'                     # 8: still code (the regex did not open a comment)
            'const t = `a // ${ {b: 1}.b } c`;\n'  # 9
            'x = y / z; /* end */\n')            # 10: a division, then a comment
    executable, _ = v8.line_status(text, [whole(text)])
    assert executable == {5, 7, 8, 9, 10}
    quoted = 'const g = "/*";\nconst h = \'*/\' + `/*`;\nconst i = 3;\n'  # comment markers inside strings
    assert v8.line_status(quoted, [whole(quoted)])[0] == {1, 2, 3}


def test_lines_in_the_comment_itself_never_run():
    text = 'const a = 1; /* note:\n   still the note */\n'
    executable, ran = v8.line_status(text, [whole(text)])
    assert executable == ran == {1}


# -- reading the coverage directory (untrusted) -------------------------------------------------------------------

def _report(ws, name, data):
    path = ws / COV / name
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    return path


def _script(url, ranges):
    return {'scriptId': '1', 'url': url, 'functions': [
        {'functionName': '', 'isBlockCoverage': True,
         'ranges': [{'startOffset': s, 'endOffset': e, 'count': c} for s, e, c in ranges]}]}


def _fold(tmp_path, ident, text='x = 1', **kw):
    return v8.fold(tmp_path, COV, ident, str(tmp_path), {'m.js': text}, **kw)


def test_reports_are_read_from_the_directory_prepared_for_them(tmp_path):
    ident = v8.prepare(tmp_path, COV)
    url = (tmp_path / 'm.js').as_uri()
    _report(tmp_path, 'coverage-1.json', {'result': [_script(url, [(0, 5, 1)]), _script('node:fs', [(0, 1, 1)])]})
    folded = _fold(tmp_path, ident, present={'other.js'})
    assert folded.seen == {'m.js'} and folded.accumulators['m.js'].entries == 1
    assert folded.accumulators['m.js'].line_status() == ({1}, {1})


@pytest.mark.parametrize('content, reason', [
    ('{"result": [', 'not valid JSON'),
    ('\xff\xfe', 'not valid JSON'),
    ('[1, 2]', 'no result list'),
    ('{"result": {}}', 'no result list'),
])
def test_a_malformed_coverage_file_is_unavailable(tmp_path, content, reason):
    ident = v8.prepare(tmp_path, COV)
    _report(tmp_path, 'coverage-1.json', content)
    with pytest.raises(v8.Unavailable, match=reason):
        _fold(tmp_path, ident)


@pytest.mark.parametrize('ranges', [
    [{'startOffset': 5, 'endOffset': 1, 'count': 1}],
    [{'startOffset': -1, 'endOffset': 1, 'count': 1}],
    [{'startOffset': 0, 'endOffset': 1, 'count': True}],
    [{'startOffset': '0', 'endOffset': 1, 'count': 1}],
    [{'startOffset': 0, 'endOffset': 1}],
    'nope', [],
])
def test_a_malformed_entry_for_a_watched_file_is_unavailable_and_others_are_ignored(tmp_path, ranges):
    url = (tmp_path / 'm.js').as_uri()
    bad = {'url': url, 'functions': [{'ranges': ranges}]}
    with pytest.raises(v8.Unavailable, match='malformed'):
        v8.scripts_for([[bad]], str(tmp_path), {'m.js'})
    assert v8.scripts_for([[bad, 'junk', None]], str(tmp_path), {'other.js'}) == {}


def test_no_coverage_written_is_unavailable_not_an_empty_record(tmp_path):
    ident = v8.prepare(tmp_path, COV)
    with pytest.raises(v8.Unavailable, match='no coverage was written'):
        _fold(tmp_path, ident)


def test_oversized_coverage_is_unavailable(tmp_path, monkeypatch):
    ident = v8.prepare(tmp_path, COV)
    _report(tmp_path, 'coverage-1.json', {'result': [], 'pad': 'x' * 400})
    monkeypatch.setattr(v8, 'MAX_FILE_BYTES', 100)
    with pytest.raises(v8.Unavailable, match='larger than'):
        _fold(tmp_path, ident)
    monkeypatch.setattr(v8, 'MAX_FILE_BYTES', 1000)
    monkeypatch.setattr(v8, 'MAX_TOTAL_BYTES', 600)  # (2 GiB in use: each file is folded and dropped in turn)
    _report(tmp_path, 'coverage-2.json', {'result': [], 'pad': 'x' * 400})
    with pytest.raises(v8.Unavailable, match='coverage output is larger'):
        _fold(tmp_path, ident)


def test_too_many_coverage_files_is_unavailable(tmp_path, monkeypatch):
    ident = v8.prepare(tmp_path, COV)
    for n in range(3):
        _report(tmp_path, f'coverage-{n}.json', {'result': []})
    with pytest.raises(v8.Unavailable, match='more than 2 coverage files'):
        _fold(tmp_path, ident, max_files=2)
    assert _fold(tmp_path, ident, max_files=3).seen == set()


@pytest.mark.skipif(not hasattr(os, 'symlink'), reason='needs symbolic links')
def test_a_symbolic_link_in_the_coverage_output_is_refused(tmp_path):
    ident = v8.prepare(tmp_path, COV)
    (tmp_path / 'elsewhere.json').write_text('{"result": []}')
    os.symlink(tmp_path / 'elsewhere.json', tmp_path / COV / 'coverage-1.json')
    with pytest.raises(v8.Unavailable, match='symbolic link'):
        _fold(tmp_path, ident)


@pytest.mark.skipif(not hasattr(os, 'symlink'), reason='needs symbolic links')
def test_a_coverage_directory_replaced_by_a_link_or_another_directory_is_refused(tmp_path):
    ident = v8.prepare(tmp_path, COV)
    other = tmp_path / 'other'
    other.mkdir()
    (other / 'coverage-1.json').write_text('{"result": []}')
    shutil.rmtree(tmp_path / COV)
    os.symlink(other, tmp_path / COV)
    with pytest.raises(v8.Unavailable, match='not a directory'):
        _fold(tmp_path, ident)
    os.unlink(tmp_path / COV)
    (tmp_path / COV).mkdir()
    (tmp_path / COV / 'coverage-1.json').write_text('{"result": []}')
    if v8._dir_identity(tmp_path, COV) != ident:  # a filesystem may reuse the inode
        with pytest.raises(v8.Unavailable, match='replaced during the run'):
            _fold(tmp_path, ident)


def test_something_other_than_a_coverage_file_in_the_directory_is_refused(tmp_path):
    ident = v8.prepare(tmp_path, COV)
    (tmp_path / COV / 'sub').mkdir()
    with pytest.raises(v8.Unavailable, match='something other than coverage files'):
        _fold(tmp_path, ident)


def test_a_directory_that_already_holds_files_is_not_prepared(tmp_path):
    (tmp_path / COV).mkdir(parents=True)
    (tmp_path / COV / 'coverage-0.json').write_text('{"result": []}')
    with pytest.raises(v8.Unavailable, match='not empty'):
        v8.prepare(tmp_path, COV)


# -- against real V8 output (verifies the UTF-16, CRLF and byte-order-mark assumptions instead of assuming them) ---

@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_real_v8_coverage_maps_to_the_expected_lines(tmp_path):
    cjs = ('﻿// \U0001F600 é\r\n'          # 1 comment (BOM kept by CommonJS)
           'const s = "\U0001F600\U0001F600";\r\n'   # 2
           'exports.f = (a) => {\r\n'                # 3
           '  if (a > 5) {\r\n'                      # 4
           '    return "é\U0001F600";\r\n'      # 5 never: a is 1
           '  }\r\n'                                 # 6
           '  return 2;\r\n'                         # 7
           '};\r\n'                                  # 8
           'function never() {\r\n'                  # 9
           '  return 3;\r\n'                         # 10
           '}\r\n')                                  # 11
    esm = ('﻿const s = "\U0001F600";\n'         # 1 (BOM dropped by the ES module loader)
           'export const h = (a) => {\n'             # 2
           '  if (a) { return "é"; }\n'         # 3 the block never runs; the line's condition does
           '  return 0;\n'                           # 4
           '};\n'                                    # 5
           'export const k = () => 1;\n')            # 6 k is never called, but the export line ran
    (tmp_path / 'm.js').write_bytes(cjs.encode('utf-8'))
    (tmp_path / 'e.mjs').write_bytes(esm.encode('utf-8'))
    (tmp_path / 'm.test.js').write_text(
        "const t = require('node:test');\nconst assert = require('node:assert');\nconst {f} = require('./m.js');\n"
        "t('f', async () => { assert.equal(f(1), 2); const {h} = await import('./e.mjs'); h(0); });\n")
    ident = v8.prepare(tmp_path, COV)
    env = {**os.environ, 'NODE_V8_COVERAGE': str(tmp_path / COV)}
    out = subprocess.run(['node', '--test', 'm.test.js'], cwd=tmp_path, env=env, capture_output=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    root = str(tmp_path.resolve())
    folded = v8.fold(tmp_path, COV, ident, root, {'m.js': cjs, 'e.mjs': esm}, present={'m.test.js'})
    assert folded.seen == {'m.js', 'e.mjs', 'm.test.js'}
    assert folded.accumulators['m.js'].line_status() == ({2, 3, 4, 5, 7, 9, 10}, {2, 3, 4, 7})
    assert folded.accumulators['e.mjs'].line_status() == ({1, 2, 3, 4, 6}, {1, 2, 3, 4, 6})


# -- review of #146: bounded work on hostile input, parser robustness, one definition of an executable line --------

def test_hostile_ranges_and_duplicate_entries_are_bounded_and_fast(tmp_path):
    import time
    text = 'x = 1;\n' * 2000
    n = u16(text)
    started = time.process_time()  # CPU time: a loaded host must not fail the bound
    with pytest.raises(v8.Unavailable, match='more ranges than its text can hold'):
        v8.line_status(text, [tuple([(0, n, 1)] + [(i % n, n, i % 2) for i in range(v8.RANGES_PER_UNIT * n + 100)])])
    # identical ranges and identical entries count once (400k ranges: about what the byte cap lets through)
    url = (tmp_path / 'm.js').as_uri()
    dup = {'url': url, 'functions': [{'ranges': [{'startOffset': 0, 'endOffset': n, 'count': 1}] * 2000}]}
    assert v8.scripts_for([[dup] * 200], str(tmp_path), {'m.js'}) == {'m.js': [((0, n, 1),)]}
    # the most ranges a file may have (overlapping at random, as hostile output would) still maps quickly
    import random
    rnd = random.Random(1)
    ranges = [(0, n, 1)]
    for _ in range(v8.RANGES_PER_UNIT * n):
        a = rnd.randrange(n)
        ranges.append((a, rnd.randrange(a, n + 1), rnd.randrange(2)))
    v8.line_status(text, [tuple(ranges)])
    assert time.process_time() - started < 1.0


def test_many_entries_fold_into_one_map_and_total_ranges_are_bounded(tmp_path, monkeypatch):
    """Re-review of #146: a whole suite writes one entry per test-file process (counts differ, so entries differ);
    the per-entry range bound must not add up over entries, and memory must not grow with them."""
    ident = v8.prepare(tmp_path, COV)
    url = (tmp_path / 'm.js').as_uri()
    text = 'a;\nb;\n'
    for n in range(100):  # 100 processes: each ran line 1, every 10th also line 2
        _report(tmp_path, f'coverage-{n}.json', {'result': [_script(url, [(0, 6, 1 + n), (3, 6, int(n % 10 == 0))])]})
    acc = _fold(tmp_path, ident, text).accumulators['m.js']
    assert acc.entries == 100 and acc.line_status() == ({1, 2}, {1, 2}) and len(acc._patterns) == 2
    assert v8.line_status(text, [((0, 6, n), (3, 6, 0)) for n in range(1, 200)]) == ({1, 2}, {1})
    monkeypatch.setattr(v8, 'MAX_TOTAL_RANGES', 150)
    with pytest.raises(v8.Unavailable, match='more than 150 ranges'):
        _fold(tmp_path, ident, text)


def test_a_passed_deadline_stops_reading_and_mapping(tmp_path):
    import time
    ident = v8.prepare(tmp_path, COV)
    _report(tmp_path, 'coverage-1.json', {'result': []})
    with pytest.raises(v8.Unavailable, match='no time was left'):
        _fold(tmp_path, ident, deadline=time.monotonic() - 1)
    with pytest.raises(v8.Unavailable, match='no time was left'):
        v8.line_status('a;\n', [((0, 3, 1),)], deadline=time.monotonic() - 1)


def test_an_entry_whose_url_does_not_parse_is_skipped(tmp_path):
    good = _script((tmp_path / 'm.js').as_uri(), [(0, 3, 1)])
    assert v8.scripts_for([[_script('file://[x/m.js', [(0, 3, 1)]), good]], str(tmp_path), {'m.js'}) == \
        {'m.js': [((0, 3, 1),)]}


def test_a_lenient_read_skips_malformed_files_and_entries(tmp_path):
    ident = v8.prepare(tmp_path, COV)
    url = (tmp_path / 'm.js').as_uri()
    _report(tmp_path, 'coverage-1.json', '{')
    _report(tmp_path, 'coverage-2.json', {'result': [{'url': url, 'functions': 'nope'}, _script(url, [(0, 3, 1)])]})
    _report(tmp_path, 'coverage-3.json', {'result': [_script(url, [(0, 99, 1)])]})  # does not fit the text: skipped
    acc = _fold(tmp_path, ident, 'a;\n', lenient=True).accumulators['m.js']
    assert acc.entries == 1 and acc.never_run() == ({1}, set())
    with pytest.raises(v8.Unavailable):
        _fold(tmp_path, ident, 'a;\n')


def test_a_postfix_increment_before_a_slash_is_a_division_and_cannot_open_a_fake_comment():
    text = ("x++ / 2; y = s.replace(/\\/*/g, '');\n"   # 1: division, then a regex holding /*
            'const a = 1;\n'                         # 2
            'z-- / 3; const b = "*/";\n'             # 3
            'const c = 2;\n')                        # 4
    assert v8.executable_lines(text) == {1, 2, 3, 4}
    unclosed = 'const p = q /* never closed\nconst r = 1;\n'  # a misread /* with no */ hides nothing
    assert v8.executable_lines(unclosed) == {1, 2}


def test_never_run_is_the_block_precise_view_with_the_same_executable_lines():
    text = 'const s = "' + '\U0001F600' * 12 + '";\nexports.a = (x) => {\n  if (x) n();\n  return 1;\n};\n/* a\n note */\n'
    entry = ((0, u16(text), 1), (at(text, '(x) =>'), at(text, '};') + 1, 1), (at(text, 'n();'), at(text, '\n  return'), 0))
    executable, never = v8.never_run(text, [entry])
    assert executable == {1, 2, 3, 4} == v8.executable_lines(text) and never == {3}
    assert v8.never_run(text, []) == ({1, 2, 3, 4}, {1, 2, 3, 4}), 'a file no entry covers never ran'
    # an entry that does not match the text is skipped (only more lines can read as never run), not trusted
    assert v8.never_run(text, [((0, u16(text) + 5, 1),)])[1] == {1, 2, 3, 4}


def test_a_regex_right_after_a_condition_is_not_a_division_but_after_other_parentheses_it_is():
    """Re-review of #146: `if (x) /[/*]/.test(s)` read as division plus a comment hid lines up to the next `*/`."""
    text = ('if (x) /[/*]/.test(s);\n'         # 1: a regex after the condition's `)`
            'const a = 1;\n'                   # 2: must stay visible
            'const b = (a) / 2; /* c */\n'     # 3: a division after an ordinary `)`, then a comment
            'while (f(a)) /x/.exec(s);\n'      # 4: nested parentheses inside the condition
            'const d = (g(1)) / 3 / 4;\n'      # 5
            'const e = 5; // */\n')            # 6
    assert v8.executable_lines(text) == {1, 2, 3, 4, 5, 6}
    assert sum(v8.code_mask(text)[text.index('/* c */'):text.index('/* c */') + 7]) == 0


# -- containers: paths the sandbox reports are mapped back to repo-relative paths exactly ---------------------------

@pytest.mark.parametrize('path, expected', [
    ('/work/pick.js', 'pick.js'),
    ('/work/src/a b/m.js', 'src/a b/m.js'),
    ('/work', None),                       # the root itself is no file
    ('/work/', None),
    ('/work2/pick.js', None),              # a sibling that shares the prefix text
    ('/workpick.js', None),
    ('/work/../etc/passwd', None),         # resolves outside
    ('/work/a/../pick.js', None),          # would resolve inside, but is not canonical: refused, never normalised
    ('/work/./pick.js', None),
    ('/work//pick.js', None),
    ('/work/pick.js/', None),
    ('/work/a\\b.js', None),
    ('/work/a\x00.js', None),
    ('work/pick.js', None),
    ('/elsewhere/pick.js', None),
])
def test_an_in_container_path_maps_only_when_strictly_inside_the_workspace(path, expected):
    assert v8.inside_rel(path, '/work') == expected
    assert v8.inside_rel(path, '/work/') == expected


def test_a_host_sandbox_path_maps_the_same_way_and_a_relative_root_maps_nothing():
    assert v8.inside_rel('/private/tmp/ws-1/pick.js', '/private/tmp/ws-1') == 'pick.js'
    assert v8.inside_rel('/private/tmp/ws-10/pick.js', '/private/tmp/ws-1') is None
    assert v8.inside_rel('/work/pick.js', 'work') is None


@pytest.mark.parametrize('key, expected', [
    ('m.py', 'm.py'), ('src/pkg/m.py', 'src/pkg/m.py'),
    ('/work/m.py', None), ('../m.py', None), ('a/../m.py', None), ('./m.py', None), ('a//m.py', None),
    ('', None), ('a\\m.py', None), (None, None), (3, None),
])
def test_a_tracer_key_is_used_only_as_a_canonical_relative_path(key, expected):
    assert v8.safe_rel(key) == expected


def test_container_coverage_urls_map_to_the_workspace_and_others_are_ignored():
    def entry(url):
        return {'url': url, 'functions': [{'ranges': [{'startOffset': 0, 'endOffset': 3, 'count': 1}]}]}
    urls = ['file:///work/pick.js', 'file:///work/%2e%2e/work/pick.js', 'file:///work/./pick.js',
            'file://host/work/pick.js', 'file:///work/node_modules/x/pick.js', 'file:///work2/pick.js',
            'file:///work/pick.js?v=2']
    found = v8.scripts_for([[entry(u) for u in urls]], '/work', {'pick.js'})
    assert found == {'pick.js': [((0, 3, 1),)]}, 'only the exact paths (the query is the same file) count'
    assert v8.scripts_for([[entry('file:///work/%2e%2e/work/pick.js')]], '/work', {'pick.js'}) == {}

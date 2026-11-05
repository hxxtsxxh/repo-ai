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


def test_reports_are_read_from_the_directory_prepared_for_them(tmp_path):
    ident = v8.prepare(tmp_path, COV)
    url = (tmp_path / 'm.js').as_uri()
    _report(tmp_path, 'coverage-1.json', {'result': [_script(url, [(0, 5, 1)]), _script('node:fs', [(0, 1, 1)])]})
    reports = v8.read_reports(tmp_path, COV, ident)
    assert v8.scripts_for(reports, str(tmp_path), {'m.js'}) == {'m.js': [[(0, 5, 1)]]}
    assert v8.scripts_for(reports, str(tmp_path), {'other.js'}) == {}


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
        v8.read_reports(tmp_path, COV, ident)


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
        v8.read_reports(tmp_path, COV, ident)


def test_oversized_coverage_is_unavailable(tmp_path, monkeypatch):
    ident = v8.prepare(tmp_path, COV)
    _report(tmp_path, 'coverage-1.json', {'result': [], 'pad': 'x' * 400})
    monkeypatch.setattr(v8, 'MAX_FILE_BYTES', 100)
    with pytest.raises(v8.Unavailable, match='larger than'):
        v8.read_reports(tmp_path, COV, ident)
    monkeypatch.setattr(v8, 'MAX_FILE_BYTES', 1000)
    monkeypatch.setattr(v8, 'MAX_TOTAL_BYTES', 600)
    _report(tmp_path, 'coverage-2.json', {'result': [], 'pad': 'x' * 400})
    with pytest.raises(v8.Unavailable, match='coverage output is larger'):
        v8.read_reports(tmp_path, COV, ident)


def test_too_many_coverage_files_is_unavailable(tmp_path, monkeypatch):
    ident = v8.prepare(tmp_path, COV)
    monkeypatch.setattr(v8, 'MAX_FILES', 2)
    for n in range(3):
        _report(tmp_path, f'coverage-{n}.json', {'result': []})
    with pytest.raises(v8.Unavailable, match='more than 2 coverage files'):
        v8.read_reports(tmp_path, COV, ident)


@pytest.mark.skipif(not hasattr(os, 'symlink'), reason='needs symbolic links')
def test_a_symbolic_link_in_the_coverage_output_is_refused(tmp_path):
    ident = v8.prepare(tmp_path, COV)
    (tmp_path / 'elsewhere.json').write_text('{"result": []}')
    os.symlink(tmp_path / 'elsewhere.json', tmp_path / COV / 'coverage-1.json')
    with pytest.raises(v8.Unavailable, match='symbolic link'):
        v8.read_reports(tmp_path, COV, ident)


@pytest.mark.skipif(not hasattr(os, 'symlink'), reason='needs symbolic links')
def test_a_coverage_directory_replaced_by_a_link_or_another_directory_is_refused(tmp_path):
    ident = v8.prepare(tmp_path, COV)
    other = tmp_path / 'other'
    other.mkdir()
    (other / 'coverage-1.json').write_text('{"result": []}')
    shutil.rmtree(tmp_path / COV)
    os.symlink(other, tmp_path / COV)
    with pytest.raises(v8.Unavailable, match='not a directory'):
        v8.read_reports(tmp_path, COV, ident)
    os.unlink(tmp_path / COV)
    (tmp_path / COV).mkdir()
    (tmp_path / COV / 'coverage-1.json').write_text('{"result": []}')
    if v8._dir_identity(tmp_path, COV) != ident:  # a filesystem may reuse the inode
        with pytest.raises(v8.Unavailable, match='replaced during the run'):
            v8.read_reports(tmp_path, COV, ident)


def test_something_other_than_a_coverage_file_in_the_directory_is_refused(tmp_path):
    ident = v8.prepare(tmp_path, COV)
    (tmp_path / COV / 'sub').mkdir()
    with pytest.raises(v8.Unavailable, match='something other than coverage files'):
        v8.read_reports(tmp_path, COV, ident)


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
    scripts = v8.scripts_for(v8.read_reports(tmp_path, COV, ident), root, {'m.js', 'e.mjs', 'm.test.js'})
    assert set(scripts) == {'m.js', 'e.mjs', 'm.test.js'}
    assert v8.line_status(cjs, scripts['m.js']) == ({2, 3, 4, 5, 7, 9, 10}, {2, 3, 4, 7})
    assert v8.line_status(esm, scripts['e.mjs']) == ({1, 2, 3, 4, 6}, {1, 2, 3, 4, 6})

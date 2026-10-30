"""Regressions encountered in upstream Cachetools and Marked installed journeys."""
import hashlib
import json

from conftest import _git
from repo_ai.mission import runtime, verification
from repo_ai.verify import results
from repo_ai.verify.runner import parse_command
from test_verify_adaptive import _shim


def test_inherited_unittest_methods_have_collected_file_identity(tmp_path):
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests/__init__.py').write_text('import unittest\nclass Shared(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n')
    (tmp_path / 'tests/test_child.py').write_text('from . import Shared\nclass Child(Shared): pass\n')
    code, report = _shim(tmp_path, '-m', 'pytest')
    runner = parse_command('python -m pytest')
    files = ['tests/test_child.py']
    att = results.parse(report, runner, files, str(tmp_path), exit_code=code, timed_out=False)
    outcomes, reasons = verification._outcomes(report, runner, files, str(tmp_path), att)
    assert not reasons, reasons
    assert len(outcomes) == 2
    assert all(key.startswith('tests/test_child.py::') for key in outcomes)


def test_typescript_tokenizer_identifiers_are_not_credentials(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    before = 'const tokenizer = this.defaults.tokenizer;\nexport const run = () => 1;\n'
    after = before.replace('=> 1', '=> 2')
    (root / 'parser.ts').write_text(before)
    (root / 'parser.test.js').write_text("import {test} from 'node:test'; test('x',()=>{});\n")
    _git(root, 'init', '-q')
    _git(root, 'add', '.')
    _git(root, 'commit', '-qm', 'base')
    plan = runtime.plan(root, 'repair parser.ts', agent='replay', write_paths=['parser.ts'], command='node --test')
    patch = tmp_path / 'proposal.json'
    patch.write_text(json.dumps({'schema':'repo-ai.replay/1','label':'replay','edits':[{
        'path':'parser.ts','before_sha256':hashlib.sha256(before.encode()).hexdigest(),'after':after}]}))
    assert runtime.proposal(patch, root, runtime.decode(plan['contract']))['edits'][0]['after'] == after


def test_source_filter_still_blocks_quoted_credentials_and_comments():
    from repo_ai.security import source_contains_secret
    assert source_contains_secret('parser.ts', 'const api_token = "long-sensitive-credential";')
    assert source_contains_secret('parser.ts', '// token=long-sensitive-credential')
    assert source_contains_secret('parser.py', 'password = "x9#mK2$pL8@vQ5!nR7^wT4&yU6*zB3(cF1"')
    assert not source_contains_secret('parser.ts', 'const tokens = genericToken[childTokens].flat(Infinity);')


def test_inherited_method_not_attributed_to_unlisted_file(tmp_path):
    """Negative control: outcomes from a file outside the approved list never pass."""
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests/__init__.py').write_text('import unittest\nclass Shared(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n')
    (tmp_path / 'tests/test_child.py').write_text('from . import Shared\nclass Child(Shared): pass\n')
    (tmp_path / 'tests/test_other.py').write_text('def test_other(): pass\n')
    code, report = _shim(tmp_path, '-m', 'pytest')
    runner = parse_command('python -m pytest')
    files = ['tests/test_other.py']
    att = results.parse(report, runner, files, str(tmp_path), exit_code=code, timed_out=False)
    outcomes, reasons = verification._outcomes(report, runner, files, str(tmp_path), att)
    assert reasons
    assert not any(key.startswith('tests/test_other.py::') and 'Shared' in key for key in outcomes)


def test_source_filter_keeps_old_protection_for_config_and_other_comment_styles():
    """Regression found by independent review of 8be7808: the narrowed filter dropped these."""
    from repo_ai.security import source_contains_secret
    secret = 'MyS3cur3P1234567890'
    for path, text in [
        ('q.sql', f'-- password: {secret}'),
        ('p.html', f'<!-- api_key: {secret} -->'),
        ('a.c', f'/* password = {secret} */'),
        ('a.js', f'/**\n * password: {secret}\n */'),
        ('c.yml', f'password: {secret}'),
        ('a.env', f'API_TOKEN={secret}'),
        ('settings.ini', 'password = correcthorsebatterystaple'),
        ('a.ts', f'const api_token = "{secret}";'),
    ]:
        assert source_contains_secret(path, text), (path, text)


def test_source_filter_still_allows_ordinary_identifiers_and_expressions():
    from repo_ai.security import source_contains_secret
    for path, text in [
        ('parser.ts', 'const tokenizer = this.defaults.tokenizer;'),
        ('parser.ts', 'const tokenizer = defaultTokenizer;'),
        ('a.py', "token = os.environ['X']"),
        ('a.py', 'secret_key = load_secret_key(path)'),
        ('a.ts', 'let i = n--; // decrement'),
        ('a.sql', '-- select the tokens table'),
    ]:
        assert not source_contains_secret(path, text), (path, text)

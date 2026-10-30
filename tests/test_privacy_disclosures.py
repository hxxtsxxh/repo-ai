"""Privacy disclosure covers network and retained artifacts, not just regexes."""
from repo_ai.config import load_config
from repo_ai.paths import resolve_layout
from repo_ai.privacy import audit, render


def test_audit_discloses_provider_and_retained_surfaces(pyweb):
    cfg = load_config(pyweb)
    stores = audit(pyweb, cfg, resolve_layout(pyweb, cfg))
    by_name = {s.name: s for s in stores}
    mission = by_name['missions (experimental)'].contains
    assert 'no provider upload' not in mission
    assert 'task text' in mission and 'diffs' in mission
    assert 'provider' in by_name['provider transmission'].contains
    assert 'network' in by_name['provider transmission'].contains
    assert 'readable' in by_name['provider transmission'].contains
    assert 'uninstall' in by_name['user exports'].retention
    assert 'zone' in by_name['provider transmission'].contains
    text = render(stores)
    assert 'not a complete secret' in text
    assert 'remove everything' not in text


def test_size_survives_files_deleted_while_it_walks(tmp_path, monkeypatch):
    """`privacy audit` must not crash when another process deletes a file between the directory walk and stat()."""
    from pathlib import Path

    from repo_ai import privacy

    (tmp_path / 'keep.txt').write_text('abc')
    (tmp_path / 'gone.txt').write_text('12345')
    real_stat, real_is_file = Path.stat, Path.is_file

    # The walk saw the file (is_file True) but it is gone by the time its size is read (stat raises). Patching both
    # keeps the test independent of how a given Python version's pathlib implements is_file().
    def vanished_is_file(self, *args, **kwargs):
        return True if self.name == 'gone.txt' else real_is_file(self, *args, **kwargs)

    def vanished_stat(self, *args, **kwargs):
        if self.name == 'gone.txt':
            raise FileNotFoundError(2, 'No such file or directory', self.name)
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'is_file', vanished_is_file)
    monkeypatch.setattr(Path, 'stat', vanished_stat)
    size, count = privacy._size(tmp_path)
    assert size == 3 and count == 1      # the vanished file is simply not counted

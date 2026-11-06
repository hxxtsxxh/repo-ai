import pytest

SAMPLE = """\
2026-03-04T10:00:00Z INFO web: started on port 8080
2026-03-04T10:00:05Z DEBUG db: pool size 4
2026-03-04T10:01:00Z WARNING db: slow query took 1200 ms
2026-03-04T10:02:00Z ERROR db: connection 17 lost
2026-03-04T10:02:30Z ERROR db: connection 18 lost

2026-03-04T10:03:00Z INFO healthcheck: ok
2026-03-04T10:04:00Z ERROR web: request 991 failed
2026-03-04T10:05:00Z CRITICAL web: worker crashed
"""


@pytest.fixture
def sample_log(tmp_path):
    path = tmp_path / "app.log"
    path.write_text(SAMPLE, encoding="utf-8")
    return path

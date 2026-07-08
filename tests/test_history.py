from localflow import history


def test_add_and_recent(tmp_path):
    db = tmp_path / "h.db"
    history.add("Hello world", raw_text="hello world", app_name="Slack",
                audio_seconds=1.2, elapsed_seconds=0.8, db_path=db)
    history.add("Second one", app_name="Notes", db_path=db)
    entries = history.recent(10, db_path=db)
    assert len(entries) == 2
    assert entries[0]["text"] == "Second one"  # newest first
    assert entries[1]["app_name"] == "Slack"
    assert history.count(db_path=db) == 2


def test_clear(tmp_path):
    db = tmp_path / "h.db"
    history.add("something", db_path=db)
    history.clear(db_path=db)
    assert history.count(db_path=db) == 0


def test_render_library(tmp_path):
    db = tmp_path / "h.db"
    out = tmp_path / "lib.html"
    history.add("Ship the <creative> report", app_name="Slack", db_path=db)
    path = history.render_library(db_path=db, out_path=out)
    content = path.read_text()
    assert "Ship the &lt;creative&gt; report" in content  # escaped
    assert "1 dictations" in content


def test_render_empty_library(tmp_path):
    out = history.render_library(db_path=tmp_path / "h.db", out_path=tmp_path / "lib.html")
    assert "0 dictations" in out.read_text()

from pathlib import Path
import pytest
from pa.core.store import Store

@pytest.fixture
async def store(tmp_path: Path):
    s = Store(tmp_path / "test.db")
    await s.connect()
    await s.init_schema()
    yield s
    await s.close()

async def test_connect_and_init(store):
    rows = await store.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
    table_names = {r["name"] for r in rows}
    assert "recipes" in table_names
    assert "query_templates" in table_names

async def test_execute_and_fetchall(store):
    await store.execute(
        "INSERT INTO recipes (plugin, name, steps) VALUES (?, ?, ?)",
        ("test", "test_recipe", "[]"),
    )
    rows = await store.fetchall("SELECT * FROM recipes WHERE plugin = ?", ("test",))
    assert len(rows) == 1
    assert rows[0]["name"] == "test_recipe"

async def test_fetchone(store):
    await store.execute(
        "INSERT INTO recipes (plugin, name, steps) VALUES (?, ?, ?)",
        ("test", "r1", "[]"),
    )
    row = await store.fetchone("SELECT * FROM recipes WHERE name = ?", ("r1",))
    assert row is not None
    assert row["plugin"] == "test"

async def test_fetchone_returns_none(store):
    row = await store.fetchone("SELECT * FROM recipes WHERE name = ?", ("nope",))
    assert row is None

async def test_execute_returns_lastrowid(store):
    result = await store.execute(
        "INSERT INTO recipes (plugin, name, steps) VALUES (?, ?, ?)",
        ("test", "r2", "[]"),
    )
    assert result > 0

async def test_init_plugin_schema(store):
    ddl = "CREATE TABLE IF NOT EXISTS myplugin_items (id INTEGER PRIMARY KEY AUTOINCREMENT, value TEXT NOT NULL);"
    await store.init_plugin_schema("myplugin", ddl)
    rows = await store.fetchall("SELECT name FROM sqlite_master WHERE type='table' AND name='myplugin_items'")
    assert len(rows) == 1

async def test_init_plugin_schema_rejects_bad_ddl(store):
    with pytest.raises(ValueError, match="disallowed"):
        await store.init_plugin_schema("bad", "DROP TABLE recipes;")

async def test_init_plugin_schema_rejects_wrong_prefix(store):
    with pytest.raises(ValueError, match="must be prefixed"):
        await store.init_plugin_schema("myplugin", "CREATE TABLE other_items (id INTEGER PRIMARY KEY);")

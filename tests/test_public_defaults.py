"""First-run defaults should not apply one developer's preferences to others."""

from contextlib import closing

from app.config import Settings
from app.database import (
    add_category,
    get_all_categories,
    get_all_radar_sources,
    get_db_connection,
    init_db,
)


def test_new_install_starts_local_and_opt_in():
    assert Settings.model_fields["HOST"].default == "127.0.0.1"
    assert Settings.model_fields["LOCAL_AUTO_LOGIN"].default is False
    assert Settings.model_fields["RADAR_ENABLED"].default is False


def test_new_install_offers_neutral_categories_and_disabled_sources(isolated_runtime):
    assert [cat["name"] for cat in get_all_categories()] == ["文章", "影片", "工具", "筆記"]
    sources = get_all_radar_sources()
    assert len(sources) == 4
    assert all(not src["is_active"] for src in sources)


def test_restart_preserves_user_deleted_defaults(isolated_runtime):
    with closing(get_db_connection()) as conn, conn:
        conn.execute("DELETE FROM categories")
        conn.execute("DELETE FROM radar_sources")
    init_db()
    assert get_all_categories() == []
    assert get_all_radar_sources() == []

    add_category("我的分類")
    init_db()
    assert [cat["name"] for cat in get_all_categories()] == ["我的分類"]

"""Simplified Chinese in the AI's own text becomes Taiwan Traditional (app/zh_text.py)."""
import pytest

pytest.importorskip("opencc")

from app import zh_text  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(zh_text, "_converters", None)


def test_mixed_titles_from_the_trial_become_traditional():
    # 2026-11-18 new-user trial, analysed by a no-signup service
    assert zh_text.fix_simplified("从零手寫 GPT") == "從零手寫 GPT"
    assert zh_text.fix_simplified("Langchain-Chatchat：本地知识库问答与 Agent 应用") == \
        "Langchain-Chatchat：本地知識庫問答與 Agent 應用"


def test_traditional_text_is_left_exactly_as_it_was():
    # s2twp would turn 台灣 into 臺灣 and 發佈 into 釋出; characters Traditional also uses do not count
    for text in ("這個專案的資料夾結構與發佈流程", "台灣的游泳池，干擾不大，公里數准許", "用 `print()` 印出 json 的鍵值",
                 "uv: An extremely fast Python package manager"):
        assert not zh_text.has_simplified(text)
        assert zh_text.fix_simplified(text) == text


def test_taiwan_keeps_its_usual_character_when_fixing_mixed_text():
    assert zh_text.fix_simplified("台灣的开发者") == "台灣的開發者"
    assert zh_text.fix_simplified("臺灣的开发者") == "臺灣的開發者"


def test_fields_and_tag_lists_are_fixed_and_others_left_alone():
    record = {"title_l1": "本地知识库", "tech_tags": ["向量数据库", "RAG", 3], "category": "数据", "summary_l1": None}
    zh_text.fix_fields(record, ("title_l1", "tech_tags", "summary_l1"))
    assert record == {"title_l1": "本地知識庫", "tech_tags": ["向量資料庫", "RAG", 3], "category": "数据", "summary_l1": None}


def test_without_opencc_the_text_stays_as_it_is(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "opencc", None)
    assert zh_text.fix_simplified("本地知识库") == "本地知识库"
    assert zh_text.has_simplified("本地知识库") is False

import uuid
import pytest
from app.database import (
    init_db,
    save_item,
    get_items,
    get_status_counts,
    get_daily_review_deck,
    record_swipe,
)
from app.vector import init_vector_db, store_item_embedding, _deterministic_local_embedding
from app.brain import ask_brain, get_brain_status, format_citations_prompt


def _create_test_item(origin: str, title: str, is_read: int = 0, is_starred: int = 0) -> str:
    uid = uuid.uuid4().hex[:8]
    item_id = save_item({
        "url": f"https://e2-e3-test.invalid/{uid}",
        "source_type": "web",
        "category_name": "AI",
        "title_l1": f"{title} {uid}",
        "summary_l1": f"這是 {title} 的摘要內容，包含測試關鍵字與向量語意特徵。",
        "tech_tags": ["AI", "測試", "LLM", "架構"],
        "origin": origin,
        "is_read": is_read,
        "is_starred": is_starred,
    })
    # Store embedding for vector retrieval in testing
    emb = _deterministic_local_embedding(f"{title} AI 架構 測試", dim=256)
    store_item_embedding(item_id, emb)
    return item_id


def test_radar_triage_isolation():
    """Verify that un-starred radar items never pollute the main curated inbox."""
    init_db()
    manual_id = _create_test_item("manual", "手動收藏文章", is_read=0)
    radar_unstarred = _create_test_item("radar", "雷達自動爬取文章", is_read=0, is_starred=0)
    radar_starred = _create_test_item("radar", "雷達精選文章", is_read=0, is_starred=1)

    # 1. Curated Main List (inbox view)
    curated_items = get_items(origin="curated", limit=100)
    curated_ids = {i["id"] for i in curated_items}

    assert manual_id in curated_ids, "Manual items must appear in curated inbox"
    assert radar_starred in curated_ids, "Starred radar items must appear in curated inbox"
    assert radar_unstarred not in curated_ids, "Unstarred radar items must be isolated from curated inbox"

    # 2. Radar discovery inbox view
    radar_items = get_items(origin="radar", limit=100)
    radar_ids = {i["id"] for i in radar_items}
    assert radar_unstarred in radar_ids, "Radar items must be accessible in radar triage view"

    # 3. Status counts
    counts = get_status_counts()
    assert counts["inbox"] >= 1
    assert counts["radar"] >= 1


def test_daily_review_deck():
    """Verify daily review deck returns cards with exploration and spaced repetition."""
    init_db()
    for i in range(5):
        _create_test_item("manual", f"未讀候選 {i}", is_read=0)
    _create_test_item("manual", "已讀星標舊項目", is_read=1, is_starred=1)

    deck = get_daily_review_deck(limit=10)
    assert len(deck) > 0
    assert len(deck) <= 10

    card = deck[0]
    assert "title_l1" in card
    assert "summary_l1" in card

    # Test swipe learning integration
    test_id = card["id"]
    res = record_swipe("swipe_up", test_id, source="test")
    assert res is not None


def test_ask_brain_status_and_prompt():
    """Verify Ask Brain status check and citations prompt formatting."""
    init_db()
    status = get_brain_status()
    assert "configured_model" in status
    assert "embedding_model" in status
    assert "device_acceleration" in status

    fake_items = [
        {
            "id": "item1",
            "title_l1": "Transformer 架構全解",
            "category_name": "AI",
            "summary_l1": "深入解析注意力機制與矩陣運算",
            "tech_tags": ["Transformer", "Attention"],
            "url": "https://example.com/transformer",
        }
    ]
    formatted = format_citations_prompt(fake_items)
    assert "[1] 《Transformer 架構全解》" in formatted
    assert "深入解析注意力機制" in formatted


@pytest.mark.asyncio
async def test_ask_brain_grounded_answer(monkeypatch):
    """Verify Ask Brain returns grounded answers with citation sources."""
    init_db()
    init_vector_db()

    # Create test items in isolated DB
    item_id = _create_test_item("manual", "Transformer 注意力機制架構", is_read=0)

    # In isolated unit tests with blocked socket, mock the LLM completion
    async def mock_generate_text(self, prompt, system_prompt=None):
        return "依據文獻 [1]，Transformer 核心採用自注意力機制（Self-Attention）運算。"

    from app.providers import base
    monkeypatch.setattr(base.BaseLLMProvider, "generate_text", mock_generate_text)

    res = await ask_brain("Transformer 注意力機制", limit=3, force_cloud=True)
    assert "answer" in res
    assert len(res["answer"]) > 0
    assert "citations" in res
    assert len(res["citations"]) > 0
    first_cite = res["citations"][0]
    assert first_cite["citation_index"] == 1
    assert "Transformer" in first_cite["title"]


def test_related_items_and_knowledge_graph():
    """Verify E4 semantic neighbors and bidirectional knowledge graph."""
    init_db()
    init_vector_db()

    # Create primary item and related item
    p1 = _create_test_item("manual", "LangChain Agent 框架深入解析", is_read=0)
    p2 = _create_test_item("manual", "LangGraph 狀態機工作流架構", is_read=0)

    from app.database import get_related_items, get_item_knowledge_graph

    # 1. Related items retrieval
    related = get_related_items(p1, limit=3)
    assert len(related) > 0
    assert any(r["id"] == p2 for r in related)
    assert "similarity" in related[0]

    # 2. Knowledge graph construction
    graph = get_item_knowledge_graph(p1)
    assert "nodes" in graph
    assert "edges" in graph
    assert len(graph["nodes"]) >= 2
    center_nodes = [n for n in graph["nodes"] if n["type"] == "center"]
    assert len(center_nodes) == 1
    assert center_nodes[0]["id"] == p1

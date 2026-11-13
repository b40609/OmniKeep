"""Prompt v2.3 guards: a summary that restates its title is rewritten once, and half-width
punctuation next to Chinese becomes full-width (both picked from the owner's blind reviews)."""
from unittest.mock import AsyncMock

from app import pipeline
from app.schemas.intelligence import (full_width_punctuation, generate_structured_intelligence,
                                      sanitize_and_validate_analysis, summary_repeats_title)

TITLE = "WorldMonitor：開源即時全球情資儀表板"
ECHO = "WorldMonitor 是開源即時全球情資儀表板，整合新聞與地圖。採 AGPL-3.0，可自架。"
CLEAN = "新聞、航班與地震等 30 多種來源匯成一張即時地圖。採 AGPL-3.0，可自架並以 Ollama 跑本地模型。"


def _answer(summary, title=TITLE):
    return {"category": "Inbox", "title_l1": title, "summary_l1": summary, "tech_tags": ["OSINT"],
            "deep_analysis": "## 重點\n- 即時地圖", "is_composite": False, "sub_entities": []}


def _provider(*answers):
    provider = AsyncMock()
    provider.generate_json = AsyncMock(side_effect=list(answers))
    return provider


def test_repeats_title_catches_the_name_and_the_is_a_sentence():
    assert summary_repeats_title(TITLE, ECHO)
    assert summary_repeats_title("Python 3.15 正式推出", "Python 3.15 正式推出，帶來 JIT。")
    assert summary_repeats_title("某工具：幫你整理書籤", "這是一個開源的書籤整理工具。")
    assert not summary_repeats_title(TITLE, CLEAN)
    assert not summary_repeats_title("Gemini 3 的限制條件要放在提示詞最後", "官方指南建議把否定式指令移到結尾。")


async def test_summary_that_repeats_its_title_is_rewritten_once():
    provider = _provider(_answer(ECHO), _answer(CLEAN))
    result = await generate_structured_intelligence(provider, "prompt", "system")
    assert result["summary_l1"] == CLEAN
    second_prompt = provider.generate_json.await_args_list[1].args[0]
    assert second_prompt.startswith("prompt") and "摘要第一句重複了標題" in second_prompt


async def test_a_failed_rewrite_keeps_the_first_answer():
    provider = _provider(_answer(ECHO), RuntimeError("quota"))
    result = await generate_structured_intelligence(provider, "prompt", "system")
    assert result["summary_l1"] == ECHO
    assert provider.generate_json.await_count == 2


async def test_a_clean_summary_costs_one_call():
    provider = _provider(_answer(CLEAN))
    assert (await generate_structured_intelligence(provider, "prompt", "system"))["summary_l1"] == CLEAN
    assert provider.generate_json.await_count == 1


def test_punctuation_next_to_chinese_becomes_full_width():
    assert full_width_punctuation("支援 Ollama,可本機執行:免費!") == "支援 Ollama，可本機執行：免費！"
    assert full_width_punctuation("見 https://a.io:8080/x,共 3,000 筆") == "見 https://a.io:8080/x，共 3,000 筆"
    assert full_width_punctuation("啟動:`docker run -p 8080:80 x,y`") == "啟動：`docker run -p 8080:80 x,y`"
    fenced = "## 重點\n- 指令如下:\n```\nprint('中文,a')\n```"
    assert full_width_punctuation(fenced) == "## 重點\n- 指令如下：\n```\nprint('中文,a')\n```"


def test_validated_analysis_fixes_punctuation_in_every_text_field():
    out = sanitize_and_validate_analysis({"title_l1": "工具:用途", "summary_l1": "支援 GPU,速度快",
                                          "deep_analysis": "## 重點\n- 授權:MIT"})
    assert (out.title_l1, out.summary_l1, out.deep_analysis) == ("工具：用途", "支援 GPU，速度快", "## 重點\n- 授權：MIT")


def test_prompt_is_v2_4():
    prompt = pipeline.analysis_system_prompt()
    for part in ("## 最重要的 3 件事", "<details>", "比較表：", "流程圖：", "```mermaid", "原文未提及", "## 我可以怎麼用",
                 "summary_l1：2 到 3 句", "送出前逐項檢查", "title_l1：25 字以內", "英文單字或數字一組算 1 字"):
        assert part in prompt
    assert "\\n\\n## 最重要的 3 件事" in prompt  # the example's line breaks reach the model as JSON escapes


def test_details_sections_get_the_blank_lines_marked_needs():
    from app.schemas.intelligence import details_spacing
    tight = "## 最重要的 3 件事\n- **一**：二\n<details><summary>更多重點 1 條：授權 MIT</summary>\n- **授權**：MIT\n</details>"
    assert details_spacing(tight) == ("## 最重要的 3 件事\n- **一**：二\n\n<details>\n<summary>更多重點 1 條：授權 MIT</summary>"
                                      "\n\n- **授權**：MIT\n\n</details>")
    fenced = "<details>\n<summary>流程圖：2 步</summary>\n```mermaid\nflowchart LR\n  A[\"<details>\"] --> B\n```\n</details>"
    assert "A[\"<details>\"] --> B\n```\n\n</details>" in details_spacing(fenced)
    assert details_spacing("## 重點\n- 一") == "## 重點\n- 一"


# ── Prompt v2.5: card checks done by the program, not left to the model ──────────

def test_title_keeps_only_its_first_colon():
    from app.schemas.intelligence import single_title_colon
    assert single_title_colon("sparqlite：AI 寫出 SQLite 擴充：12 小時") == "sparqlite：AI 寫出 SQLite 擴充，12 小時"
    assert single_title_colon("Gemini 3 的限制條件要放在提示詞最後") == "Gemini 3 的限制條件要放在提示詞最後"
    assert sanitize_and_validate_analysis({"title_l1": "工具: 用途:很快", "summary_l1": "一。二。"}).title_l1 == "工具：用途，很快"


def test_card_faults_measure_display_width_and_empty_words():
    from app.schemas.intelligence import card_faults, display_width
    assert display_width("SQLite 擴充") == 11
    assert card_faults(TITLE, CLEAN) == []
    long_title = "Observability Kubernetes Prometheus Grafana：一次看懂雲端監控全套工具鏈"
    assert any("標題" in f and "太長" in f for f in card_faults(long_title, CLEAN))
    assert any("摘要太長" in f for f in card_faults(TITLE, "很長的一句話。" * 4))
    assert any("旨在" in f for f in card_faults(TITLE, "本工具旨在簡化部署。支援 Docker。"))


async def test_a_too_long_title_is_rewritten_once_and_the_shorter_kept():
    long_title = "Observability Kubernetes Prometheus Grafana：一次看懂雲端監控全套工具鏈"
    provider = _provider(_answer(CLEAN, title=long_title), _answer(CLEAN))
    result = await generate_structured_intelligence(provider, "prompt", "system")
    assert result["title_l1"] == TITLE
    assert "太長" in provider.generate_json.await_args_list[1].args[0]


async def test_a_rewrite_with_more_faults_keeps_the_first_answer():
    provider = _provider(_answer("本工具旨在簡化部署。支援 Docker。"), _answer(ECHO.replace("。", "，旨在省事。")))
    result = await generate_structured_intelligence(provider, "prompt", "system")
    assert result["summary_l1"] == "本工具旨在簡化部署。支援 Docker。"


def test_taiwan_tidy_fixes_terms_numbers_and_spacing():
    from app.schemas.intelligence import taiwan_tidy
    assert taiwan_tidy("用AI工具鏈提煉出十三步決策鏈，涵蓋信息核驗") == "用 AI 工具鏈提煉出 13 步決策鏈，涵蓋資訊核驗"
    assert taiwan_tidy("整理二十六章教學與一百二十個範例") == "整理 26 章教學與 120 個範例"
    assert taiwan_tidy("十分好用，一個工具") == "十分好用，一個工具"  # not counts
    assert taiwan_tidy("執行 `pip install x軟件` 或看 [說明](https://a.io/信息x)") == "執行 `pip install x軟件` 或看 [說明](https://a.io/信息x)"
    assert taiwan_tidy("<summary>更多重點2條</summary>") == "<summary>更多重點 2 條</summary>"


def test_a_section_with_one_point_is_unfolded_into_a_line():
    from app.schemas.intelligence import unfold_single_item_sections
    one = "## 最重要的 3 件事\n- **一**：二\n\n<details>\n<summary>限制 1 條：沒有權限管理</summary>\n\n- **單人使用**：只描述單人情境。\n\n</details>"
    assert unfold_single_item_sections(one) == "## 最重要的 3 件事\n- **一**：二\n\n**限制**：只描述單人情境。"
    two = "<details>\n<summary>更多重點 2 條：甲、乙</summary>\n\n- **甲**：一。\n- **乙**：二。\n\n</details>"
    assert unfold_single_item_sections(two) == two
    flow = "<details>\n<summary>流程圖：4 步</summary>\n\n```mermaid\nflowchart TD\n  A[\"a\"] --> B[\"b\"]\n```\n\n</details>"
    assert unfold_single_item_sections(flow) == flow


def test_a_title_with_a_step_count_is_a_fault():
    from app.schemas.intelligence import card_faults
    assert any("目錄資訊" in f for f in card_faults("加密交易復盤：AI 工具鏈與 13 步事件分析法", CLEAN))
    assert not any("目錄資訊" in f for f in card_faults("sparqlite：AI 自主 12 小時生出 SQLite 擴充", CLEAN))


def test_a_raw_newline_inside_a_json_string_is_accepted():
    import json
    raw = '{"deep_analysis": "<details>\n<summary>更多重點 2 條</summary>\n\n- a\n- b\n\n</details>"}'
    assert json.loads(raw, strict=False)["deep_analysis"].startswith("<details>\n")

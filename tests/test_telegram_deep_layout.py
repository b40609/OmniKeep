"""The deep analysis (prompt v2.4) has <details> sections, tables and mermaid flowcharts; Telegram
shows none of them, so the bot turns each into plain lines."""
from app.bot.telegram_bot import flow_steps, markdown_to_telegram_html, mermaid_steps

DEEP = """> 值得先裝。

## 最重要的 3 件事
- **只走內網**：不對外開 port。

<details>
<summary>比較表：A 最省顯存</summary>

| 模型 | 顯存 | 授權 |
| --- | --- | --- |
| A | 6 GB | MIT |
| B | 原文未提及 | Apache 2.0 |

</details>

<details>
<summary>流程圖：3 步，從收到連結到存檔</summary>

```mermaid
flowchart LR
  A["收到連結"] --> B["抓取原文"] --> C["存進資料庫"]
  A --> C
```

</details>"""


def test_details_tables_and_flowcharts_become_plain_lines():
    out = markdown_to_telegram_html(DEEP)
    assert "details" not in out and "summary" not in out and "mermaid" not in out
    assert "<b>比較表：A 最省顯存</b>" in out
    assert "模型｜顯存｜授權" in out and "B｜原文未提及｜Apache 2.0" in out and "---" not in out
    assert "收到連結 → 抓取原文 → 存進資料庫" in out
    assert "<blockquote>值得先裝。</blockquote>" in out


def test_mermaid_steps_reads_sequence_diagrams():
    code = "sequenceDiagram\n  User->>Bot: 丟連結\n  Bot-->>User: 回傳摘要"
    assert mermaid_steps(code) == ["User → Bot：丟連結", "Bot → User：回傳摘要"]


FLOW = """總結：收到連結先抓原文，正文太少就退回重抓。
段：準備
A｜開始｜收到連結｜從 Telegram 丟進來｜｜｜
B｜執行｜抓取原文｜下載網頁內容｜逾時 30 秒｜｜
C｜檢查｜抽出正文｜｜｜｜正文太少就中止
A -> B
B -> C
C -> B｜正文太少，重抓"""


def test_flow_steps_reads_step_lines_only():
    assert flow_steps(FLOW) == ["收到連結", "抓取原文", "抽出正文"]


def test_flow_blocks_become_one_line_of_steps():
    md = "<details>\n<summary>流程圖：3 步</summary>\n\n```flow\n" + FLOW + "\n```\n\n</details>"
    out = markdown_to_telegram_html(md)
    assert "收到連結 → 抓取原文 → 抽出正文" in out
    assert "｜" not in out and "->" not in out and "總結" not in out

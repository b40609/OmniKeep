# 備份與還原

OmniKeep 每天自動備份一次，必要時用 `scripts/restore_backup.py` 還原。還原前一定要先停止 OmniKeep。

## 1. 備份了什麼

| 有備份 | 沒有備份，請自己另外保存 |
|---|---|
| SQLite 資料庫：收藏、分析結果、全文索引、向量、提案、行為紀錄、推播訂閱 | `.env`：`API_KEY`、VAPID 金鑰、各家 AI 金鑰、Telegram token |
| HTML 抗腐快照：`SNAPSHOT_DIR/<項目 id>.html` | 平台登入狀態：cookie 檔、CDP 瀏覽器設定檔 |

- `.env` 建議放在密碼管理器。在新機器還原時要用**同一組** `API_KEY` 與 VAPID 金鑰。VAPID 金鑰一換，資料庫裡所有裝置的推播訂閱都會失效。
- 備份 zip **沒有加密**，裡面是你的全部資料。放到雲端時，建議使用 rclone 的 [crypt](https://rclone.org/crypt/) 遠端。

## 2. 什麼時候、備份到哪裡

- 每天 `BACKUP_HOUR`（預設 4 點）之後的第一次檢查會自動備份。也可以在監看中心的「備份」分頁按「立即備份」。
- 一律先在本機 `BACKUP_DIR` 產生 `omnikeep-backup-<時間>.zip`，再依 `BACKUP_SINK` 送出：

| `BACKUP_SINK` | 送去哪裡 | 舊備份怎麼處理 |
|---|---|---|
| `local`（預設） | 只留在 `BACKUP_DIR` | 保留最新 `BACKUP_KEEP` 份（預設 14），更舊的自動刪除 |
| `rclone` | `rclone copy` 到 `BACKUP_RCLONE_REMOTE` | 本機同上；**遠端只增不減**，要自己清，例如 `rclone delete --min-age 60d <remote>` |
| `git` | 複製到 `BACKUP_GIT_REPO_DIR` 這個 clone，commit 後 push | 本機同上；**repo 每天多一個 zip**，壓縮過的檔案 git 幾乎無法做差異壓縮，資料庫越大，repo 長得越快 |
| `off` | 不備份 | — |

git sink 的準備：先在 GitHub 等平台建一個**私人**的空 repo，clone 到本機，在那個 clone 裡設定 commit 身分，再把路徑填進 `BACKUP_GIT_REPO_DIR`。空 repo 的 clone 可以直接 push，不必先做一次 commit。

zip 內容（格式 2）：

```
omnikeep.db            用 SQLite 線上備份 API 取得的一致性快照，伺服器不必停
snapshots/<id>.html    HTML 快照
backup.json            格式版本、OmniKeep 版本、建立時間、快照數
```

`2026-11-04` 之前產生的 zip 只有 `omnikeep.db`（格式 1），也可以還原，只是不含快照。

## 3. 還原步驟

1. **停用 watchdog**：如果用工作排程器執行 `scripts/watchdog.ps1`，先停用那個工作，否則它一分鐘內就會把 OmniKeep 重新啟動。PowerShell 範例：

   ```powershell
   Get-ScheduledTask | Where-Object { $_.Actions.Arguments -match 'watchdog.ps1' } | Disable-ScheduledTask
   ```

2. **停止 OmniKeep**：關掉執行中的 `run.py`。如果還在跑，還原指令會拒絕執行，什麼都不會改動。

3. **取得備份檔**：
   - `local`：在 `BACKUP_DIR` 裡，可以直接用 `--latest`。
   - `rclone`：先下載到本機。

     ```bash
     rclone lsf <BACKUP_RCLONE_REMOTE>
     rclone copy <BACKUP_RCLONE_REMOTE>/omnikeep-backup-XXXX.zip backups/
     ```

   - `git`：`git -C <BACKUP_GIT_REPO_DIR> pull`，新機器則重新 clone。zip 就在 repo 根目錄。

4. **還原**（在專案目錄執行，使用和伺服器相同的 `.env`）：

   ```bash
   python scripts/restore_backup.py --list
   python scripts/restore_backup.py --latest
   python scripts/restore_backup.py backups/omnikeep-backup-20261104-040000-000000.zip
   ```

   指令會先顯示來源與目的地，要你輸入 `restore` 確認；加上 `--yes` 就不詢問。

5. **重新啟動 OmniKeep**，確認資料正確，再啟用 watchdog 工作：

   ```powershell
   Get-ScheduledTask | Where-Object { $_.Actions.Arguments -match 'watchdog.ps1' } | Enable-ScheduledTask
   ```

**復原這次還原**：被換掉的檔案都移到了 `BACKUP_DIR/omnikeep-prerestore-<時間>/`，對它執行同一個指令即可恢復：

```bash
python scripts/restore_backup.py backups/omnikeep-prerestore-20261104-101500-000000
```

確認不需要之後，這些資料夾可以自己刪除，程式不會自動清理。

**換到新機器**：先放好原本的 `.env`，安裝依賴並建置前端（見 README 與 `docs/tailscale_pwa_deploy.md`），再照上面的步驟還原。

**Docker**：資料在 `omnikeep_data` volume 的 `/data`。先 `docker compose stop`，再用 `docker compose run --rm omnikeep python scripts/restore_backup.py --latest --yes` 還原；服務名稱以你的 `docker-compose.yml` 為準。

## 4. 還原怎麼保護你的資料

- **伺服器在跑就拒絕**：還原期間持有佇列 worker 的檔案鎖。伺服器執行時一定持有這把鎖；還原期間就算有伺服器被啟動，也拿不到鎖，會直接失敗。
- **先檢查再動手**：zip 裡只接受 `omnikeep.db`、`backup.json`、`snapshots/<id>.html`。其他檔名一律拒絕，包括 `../` 這類路徑穿越。資料庫會先解到暫存處，要通過 `PRAGMA integrity_check` 才繼續。檢查沒過，現有資料完全不動。
- **不刪檔，只搬開**：現有的 `db`、`-wal`、`-shm` 整組移到 `omnikeep-prerestore-<時間>/`，被覆蓋的快照也一樣，之後才放入備份的資料庫。
- **不讓殘留的 WAL 弄壞資料**：資料庫檔不見、`-wal` 卻還在時，如果只把備份檔複製回去，SQLite 會把那份 WAL 重放到還原後的資料庫上。實測結果是讀到的資料被悄悄改掉，而且沒有任何錯誤。還原指令會先把 WAL 一起搬走。
- **損壞的資料庫也能換掉**：現有資料庫已經損壞時，照樣先搬開，再放入備份。
- **快照只寫回、不清空**：備份裡的快照依檔名寫回；資料夾裡備份沒有的快照保留不動。

## 5. 演練紀錄（2026-11-04）

在暫存資料上做過一次完整演練，沒有動到正式資料庫。資料是 30 筆項目、30 個向量、5 份快照、推播訂閱與行為紀錄，共 27 張資料表。

| 情境 | 結果 |
|---|---|
| 伺服器執行中，用 API 觸發備份 | 成功，zip 內有資料庫、5 份快照與 `backup.json` |
| 伺服器執行中執行還原 | 拒絕，資料沒有變動 |
| 停機後刪除整個資料夾，再 `--latest` 還原 | 27 張資料表逐列比對、快照逐檔比對都和備份前一致；重啟後 API、全文搜尋、快照都正常 |
| `BACKUP_SINK=git`，遠端是空的 bare repo | 推送成功；從新 clone 的 repo 還原，結果一致 |
| `BACKUP_SINK=rclone`，用 rclone v1.75.2 的 local 後端當遠端 | 推送、`rclone copy` 取回、還原都成功，結果一致 |

建議每隔幾個月演練一次：在另一台機器或另一個資料夾，設定好 `DATABASE_PATH`、`SNAPSHOT_DIR`、`BACKUP_DIR` 環境變數，把最新的備份還原進去並啟動確認。不要直接對正式資料庫演練。

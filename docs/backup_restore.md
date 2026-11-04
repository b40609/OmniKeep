# 備份與還原

OmniKeep 每天自動備份一次，必要時用 `scripts/restore_backup.py` 還原。還原前一定要先停止 OmniKeep。

## 1. 備份了什麼

| 有備份 | 沒有備份，請自己另外保存 |
|---|---|
| SQLite 資料庫：收藏、分析結果、全文索引、向量、提案、行為紀錄、推播訂閱 | 主金鑰檔 `omnikeep.secret.key`（資料庫旁邊） |
| 在 App「設定」輸入的值：AI 金鑰、Bot token、推播金鑰等，**加密後**存在資料庫裡 | `.env`：`API_KEY`，以及還留在 `.env` 的舊設定 |
| HTML 抗腐快照：`SNAPSHOT_DIR/<項目 id>.html` | 平台登入狀態：cookie 檔、CDP 瀏覽器設定檔 |

- 備份裡的金鑰只有加密後的內容，解密要靠主金鑰檔，而主金鑰檔刻意**不放進備份**。請把它和 `.env` 一起放在密碼管理器或另一個安全的地方。
- 只有備份、沒有主金鑰檔：收藏都還在，只是 App 內輸入的金鑰解不開。設定頁會列出哪些要重新輸入，推播金鑰則要重新產生（各裝置重新開啟推播）。
- 在新機器還原時要用**同一組** `API_KEY` 與主金鑰檔。VAPID 金鑰一換，資料庫裡所有裝置的推播訂閱都會失效。
- 備份 zip **沒有加密**（金鑰欄位除外），裡面是你的全部資料。放到雲端時，建議使用 rclone 的 [crypt](https://rclone.org/crypt/) 遠端。

### 主金鑰

- 位置：預設在資料庫旁的 `omnikeep.secret.key`，「設定 › 系統」會顯示完整路徑。可以用環境變數 `OMNIKEEP_SECRET_KEY_FILE` 指到別處，或用 `OMNIKEEP_SECRET_KEY` 直接提供（這種方式不能用下面的輪替指令）。
- 第一次在 App 儲存金鑰時自動建立。Linux、macOS 上檔案權限只限擁有者；Windows 沿用所在資料夾的權限。
- **更換（輪替）**：在伺服器的專案目錄執行

  ```bash
  python scripts/rotate_secret_key.py
  ```

  它會先把舊金鑰檔另存成 `omnikeep.secret.key.<UTC 時間>.bak`，再用新的主金鑰重新加密所有金鑰，最後把舊金鑰從金鑰檔移除。執行中的伺服器會自己偵測金鑰檔變了，不必停止或重啟。指令只印路徑和數量，不會印出任何金鑰。中途當掉的話，金鑰檔仍然讀得到所有值，再執行一次即可。
- **還原輪替之前的備份**：那份備份是用舊主金鑰加密的。把對應的 `.bak` 檔內容貼到 `omnikeep.secret.key` 的**第二行**（第一行保持現在的金鑰），還原後再執行一次 `rotate_secret_key.py`，就會全部改用新金鑰。`.bak` 要保留到比它舊的備份都不需要為止。

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

**換到新機器**：先放好原本的 `.env`，把舊主機的 `omnikeep.secret.key` 複製到新主機資料庫所在的資料夾（還原指令放資料庫的位置，也就是 `DATABASE_PATH` 的資料夾），安裝依賴並建置前端（見 README 與 `docs/tailscale_pwa_deploy.md`），再照上面的步驟還原。啟動後到「設定 › 系統」確認沒有「無法解密」的提示。

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

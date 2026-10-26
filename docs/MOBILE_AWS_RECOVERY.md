# VisualGuard：手機完成 AWS 評審端點

更新：2026-10-27，Asia/Taipei。此頁為恢復操作交接，**不是部署完成證明**。

## 現況與範圍

| 項目 | 狀態與證據 |
|---|---|
| 公開展示頁 | 已改英文、加入既有英文字幕及窄螢幕排版。gh-pages commit `994d0bd9d0f7f527343f8cdc8b15b59d32a64ed5`；瀏覽器讀回與警報案例重播成功。 |
| AWS 實際執行 | 既有私有 Lambda 的四筆合成／空輸入紀錄；部署來源 `832b1b4`，workflow `40223113044`。 |
| 最新可部署來源 | `1ec4599651f7a526408cf8e4b2a16275c16132d0`，分支 `claude/practical-ride-st6n28`。既有 CI `40391660413` 通過；本輪沒有重跑。 |
| 公開 AWS 互動 | 尚未完成。GitHub Pages 仍是保存案例重播，不呼叫 AWS。 |
| Devpost | 公開頁已顯示「SUBMITTED TO」本競賽；本輪沒有取得帳戶內最終提交收據，沒有按下提交。 |
| 本輪部署 | NOT_RUN；遠端 AWS Console 顯示 Site Unavailable，沒有可用 AWS 部署連線。 |

先完成下列兩段，再更新 Devpost 的評審入口。不要把原來的舊 Lambda 直接改為公開，因為它不是含配額的最新版。

## 1. 手機 CloudShell：準備配額表與有限權限

AWS 官方支援在 AWS Console Mobile App 首頁底部的 CloudShell 圖示，或 Services → CloudShell 開啟終端。用原本有權管理此專案的 AWS 身分登入，不需提供長期 access key。

**執行範圍：**在 `us-east-1` 建立／重用 on-demand 表 `visualguard-daily-quota`；給 runtime role 單表 `dynamodb:UpdateItem`；給 deploy role 單函式 `lambda:AddPermission/GetPolicy`。這是新的按量計費資源與有限 IAM 權限擴充。每日五次限制不是金額上限。本輪沒有代為批准新支出；請由 CEO 檢視並採取這個步驟。

程式會比對既有 AWS Function URL、runtime role、表結構與既有 inline policy，遇到不符就停止；全程維持 `AWS_IAM`，不部署、不公開、不推論。

確認上述範圍後，在手機 CloudShell 貼上：

```bash
vg_bootstrap=$(mktemp)
curl -fLsS https://raw.githubusercontent.com/mangroveuniversemu-bot/visualguard-opencv-aws/925842efee9895c8f8216f438a5b3fe59110a193/ops/aws/bootstrap_public_quota.sh -o "$vg_bootstrap" &&
printf '%s  %s\n' '99f8090ceb484e0d0817bd4117a2d218cbbb6da3a6655aad9c0277d831b465ff' "$vg_bootstrap" | sha256sum -c - &&
bash "$vg_bootstrap" --apply
```

成功必須顯示 `QUOTA_PREREQUISITES_READY`。只回報這個狀態即可，不需分享帳號、token 或完整私人日誌。若失敗，不要進入第二段；可能留下已建立的表或部分有限權限，修正後可重跑。腳本不會自行刪除資源。

只看靜態預覽時，將最後的 `--apply` 移除；這個模式沒有 AWS 呼叫。

## 2. GitHub 手機網頁：觸發既有公開部署

只有第一段成功、且本次公開與費用範圍／預算已確認後才做：

1. 開啟專案 repo → Releases → Draft a new release。
2. 新 tag：`aws-deploy-public-1`。若已存在，先查對應執行結果，不要重複送部署。
3. Target 選 `claude/practical-ride-st6n28`，確認仍為完整 SHA `1ec4599651f7a526408cf8e4b2a16275c16132d0`；若變更就先停。
4. 標題可用 `VisualGuard public judge endpoint`，檢視後 Publish release。**這會啟動既有 AWS 部署，更新容器並公開 Function URL，可能產生費用。**

不要選 `main`，也不要選本頁所在的 `codex/mobile-repair-20261027`：它只是操作輔助分支，帶有 skip-ci 提交，不是部署來源。

## 完成 Gate

- `aws-lambda` workflow 成功，部署來源為預期 SHA。
- artifact 含 `deploy.json`、`public-smoke.json`；匿名 UI/API 與配額標頭通過。既有 smoke 只用一次分析，避免耗光全訪客共用的五次額度。
- 手機免登入開啟部署結果中的 AWS URL，可載入樣本與執行 Inspect；不能只看到影片或保存重播。
- 再把該 AWS URL 放到 Devpost 評審入口，並核對正式提交狀態／收據。

若公開 smoke 失敗，先回復 Function URL 為 `AWS_IAM`，再處理問題；不要把公開函式退回無配額的舊映像。

## 驗證與來源

**INTERNAL／實際讀回：**repo、既有 CI 與已更新展示頁；新腳本尚未在真實 AWS 執行。

**DERIVED／合成驗算：**腳本 bash 語法與 14 組 fake-AWS 正負控制通過；涵蓋錯端點、錯角色、讀取被拒、表結構／billing 衝突、wait 後表被替換、最終 policy 缺失等。這不是 AWS 實測。

**PUBLIC_REFERENCE：**

- [官方競賽要求與截止](https://opencv26.devpost.com/)：頁首 2026-10-26 23:45 PDT＝台北 **10/27 14:45**；正文有 23:59 差異，採較早時間。
- [官方評分規則](https://opencv26.devpost.com/rules)：技術30%、UX10%、文件展示10%、雲端交付與重現10%等，不能保證端點缺口只影響10分。
- [AWS 手機 CloudShell](https://docs.aws.amazon.com/cloudshell/latest/userguide/working-with-aws-cloudshell.html)
- [GitHub 新建 release/tag](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)

**Exact next action：**CEO 在手機 CloudShell 檢視本次建表／權限範圍後，執行第一段；取得 `QUOTA_PREREQUISITES_READY` 才觸發原有部署。

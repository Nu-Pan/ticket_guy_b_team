# `ticket_guys_b_team` File Format Specification

## 1. 文書の目的

本書は `ticket_guys_b_team` が読み書きする主要ファイルの形式を定義する。
対象は以下とする。

* Plan file
* Ticket file
* Review result file
* Execution log file
* Codex session record file
* Last message file

本書はファイル形式と保存規約に集中し、CLI 契約や詳細な状態遷移は扱わない。

---

## 2. 基本方針

* 主要オブジェクトはファイルとして永続化する
* 主要ファイルは人間可読な形式を優先する
* 機械処理対象のログは JSON Lines または JSON を用いる
* 生成物は一貫した命名規則とディレクトリ構造に従う
* 実行失敗時も可能な限りファイルを保存する
* live 実行の記録は stub 実行にそのまま転用可能でなければならない

---

## 3. 既定ディレクトリ構造

成果物の既定配置は `artifacts/` 配下とする。

```text
artifacts/
  plans/
  tickets/
  reviews/
  logs/
  codex/
  messages/
```

各ディレクトリの役割は以下の通りとする。

* `artifacts/plans/`: 計画ファイル
* `artifacts/tickets/`: チケットファイル
* `artifacts/reviews/`: review / integration の結果ファイル
* `artifacts/logs/`: 実行ログ JSONL
* `artifacts/codex/`: Codex CLI wrapper の session record
* `artifacts/messages/`: `codex exec --output-last-message` または replay された最終メッセージのテキスト出力

---

## 4. 共通ルール

### 4.1 エンコーディング

* すべてのテキストファイルは UTF-8 を前提とする
* BOM は付与しないことを推奨する

### 4.2 改行

* 改行コードは LF を推奨する
* 実装上必要であれば読み込み時に CRLF も許容してよい

### 4.3 時刻表現

* 日時はタイムゾーン付き ISO 8601 文字列を推奨する
* 例: `2026-03-21T13:45:00+09:00`

### 4.4 識別子

* `plan_id` は一意でなければならない
* `ticket_id` は一意でなければならない
* `run_id` は `run` 実行ごとに新規採番しなければならない
* `codex_call_id` は 1 回の wrapper 呼び出しごとに一意でなければならない

### 4.5 YAML front matter

* Markdown ベースの主要ファイルは YAML front matter を先頭に持つ
* YAML front matter は `---` で開始し、`---` で終了する

---

## 5. Plan File Format

## 5.1 保存先

```text
artifacts/plans/<plan_id>.md
```

1 計画につき 1 ファイルとする。

---

## 5.2 必須メタデータ

Plan file の YAML front matter は最低限以下を含む。

* `plan_id`
* `title`
* `status`
* `created_at`
* `updated_at`

`status` は以下のいずれかでなければならない。

* `draft`
* `in_review`
* `approved`

---

## 5.3 本文構造

Plan file 本文は以下のセクションをこの順序で含む。

1. 目的
2. スコープ外
3. 成果物
4. 制約
5. 受け入れ条件
6. 作業分解
7. 未確定事項
8. 依存関係マップ
9. 想定リスク
10. 差し戻し条件
11. 検証戦略

---

## 5.4 例

```md
---
plan_id: plan-20260321-001
title: CLI 初期実装
status: draft
created_at: 2026-03-21T10:00:00+09:00
updated_at: 2026-03-21T10:00:00+09:00
---

# 目的
...

# スコープ外
...

# 成果物
...

# 制約
...

# 受け入れ条件
...

# 作業分解
...

# 未確定事項
...

# 依存関係マップ
...

# 想定リスク
...

# 差し戻し条件
...

# 検証戦略
...
```

---

## 6. Ticket File Format

## 6.1 保存先

```text
artifacts/tickets/<ticket_id>.md
```

1 チケットにつき 1 ファイルとする。

---

## 6.2 必須メタデータ

Ticket file の YAML front matter は最低限以下を含む。

* `ticket_id`
* `ticket_type`
* `status`
* `plan_id`
* `owner_role`
* `priority`

`ticket_type` は以下のいずれかでなければならない。

* `root`
* `worker`
* `review`
* `integration`

`status` は以下のいずれかでなければならない。

* `todo`
* `blocked`
* `running`
* `review_pending`
* `done`
* `failed`

---

## 6.3 推奨メタデータ

必要に応じて以下を追加してよい。

* `created_at`
* `updated_at`
* `depends_on`
* `target_ticket_id`
* `artifacts`
* `run_history`
* `default_codex_cli_mode`

ただし、依存関係の正規表現は本文の `Dependencies` セクションまたは明示的な YAML 項目のどちらか一方に統一することが望ましい。

---

## 6.4 本文構造

Ticket file 本文は以下のセクションをこの順序で含む。

1. Title
2. Purpose
3. Inputs
4. Outputs
5. Scope
6. Out of Scope
7. Dependencies
8. Steps
9. Acceptance Criteria
10. Verification
11. Risks / Notes
12. Priority
13. Owner Role
14. Blocking Conditions
15. Rollback / Abort
16. Artifacts Path

---

## 6.5 Dependencies の表現

Dependencies では、各依存を `ticket_id` と `required_state` の組で表現する。

例:

```md
# Dependencies
- ticket_id: worker-001
  required_state: review_pending
- ticket_id: review-001
  required_state: done
```

`required_state` は Ticket 状態値のいずれかでなければならない。

---

## 6.6 Artifacts Path の推奨記載

worker ticket では、少なくとも以下を Artifacts Path に記載できることが望ましい。

```md
# Artifacts Path
- artifacts/logs/worker-001-<run_id>.jsonl
- artifacts/codex/worker-001-<run_id>-<codex_call_id>.json
- artifacts/messages/worker-001-<run_id>.txt
```

---

## 6.7 例

```md
---
ticket_id: worker-001
ticket_type: worker
status: todo
plan_id: plan-20260321-001
owner_role: implementer
priority: high
default_codex_cli_mode: live
---

# Title
CLI エントリポイントを実装する

# Purpose
...

# Inputs
...

# Outputs
...

# Scope
...

# Out of Scope
...

# Dependencies
- ticket_id: root-001
  required_state: running

# Steps
...

# Acceptance Criteria
...

# Verification
...

# Risks / Notes
...

# Priority
high

# Owner Role
implementer

# Blocking Conditions
...

# Rollback / Abort
...

# Artifacts Path
- artifacts/logs/worker-001-<run_id>.jsonl
- artifacts/codex/worker-001-<run_id>-<codex_call_id>.json
- artifacts/messages/worker-001-<run_id>.txt
```

---

## 7. Review Result File Format

## 7.1 保存先

```text
artifacts/reviews/<ticket_id>.md
```

review ticket または integration ticket の結果を保存する。

---

## 7.2 必須項目

YAML front matter または本文の先頭セクションにより、最低限以下を表現しなければならない。

* 対象 `ticket_id`
* 判定結果 `pass` / `fail`
* 確認した受け入れ条件
* 残リスク
* 人間エスカレーション要否

判定不能の場合は、状態遷移上は `blocked` と扱い、本文にその理由を残さなければならない。

---

## 7.3 推奨メタデータ

* `review_ticket_id`
* `target_ticket_id`
* `plan_id`
* `created_at`
* `review_result`
* `escalation_required`

---

## 7.4 例

```md
---
review_ticket_id: review-001
target_ticket_id: worker-001
plan_id: plan-20260321-001
review_result: pass
escalation_required: false
created_at: 2026-03-21T13:20:00+09:00
---

# 確認した受け入れ条件
- pytest -q が成功すること
- CLI エントリポイントが呼び出せること

# 残リスク
- Windows 環境での PATH 差異は未確認

# 人間エスカレーション要否
false
```

---

## 8. Execution Log File Format

## 8.1 保存先

```text
artifacts/logs/<ticket_id>-<run_id>.jsonl
```

同一 `ticket_id` の再実行でも別ファイルとする。

---

## 8.2 形式

* JSON Lines を用いる
* 1 行につき 1 イベントを表す JSON object を記録する
* 成功時も失敗時も必ず保存する

---

## 8.3 必須フィールド

各 JSON object には最低限以下を含める。

* `timestamp`
* `event`
* `ticket_id`

worker 実行では、さらに以下を記録できることが望ましい。

* `codex_cli_mode`
* `codex_session_record_path`
* `replayed_from`

---

## 8.4 代表的な追加フィールド

必要に応じて以下を含める。

* `plan_id`
* `ticket_type`
* `run_id`
* `before_status`
* `after_status`
* `command`
* `returncode`
* `stdout`
* `stderr`
* `generated_artifacts`
* `stop_reason`
* `dependency_check`
* `review_result`

---

## 8.5 代表イベント

最低限、以下のイベント種別を記録できることが望ましい。

* `run_started`
* `dependency_checked`
* `status_changed`
* `codex_wrapper_started`
* `codex_wrapper_finished`
* `external_command_started`
* `external_command_finished`
* `acceptance_gate_started`
* `acceptance_gate_finished`
* `artifact_recorded`
* `run_finished`
* `run_failed`
* `blocked`

`codex_wrapper_started` / `codex_wrapper_finished` は wrapper レベルの抽象イベントであり、live / stub の差異をここで吸収する。

---

## 8.6 例

```json
{"timestamp":"2026-03-21T13:30:00+09:00","event":"run_started","ticket_id":"worker-001","plan_id":"plan-20260321-001","ticket_type":"worker","run_id":"run-0001","codex_cli_mode":"live"}
{"timestamp":"2026-03-21T13:30:01+09:00","event":"dependency_checked","ticket_id":"worker-001","dependency_check":{"result":"ok"}}
{"timestamp":"2026-03-21T13:30:02+09:00","event":"status_changed","ticket_id":"worker-001","before_status":"todo","after_status":"running"}
{"timestamp":"2026-03-21T13:30:03+09:00","event":"codex_wrapper_started","ticket_id":"worker-001","codex_cli_mode":"live","codex_call_id":"call-0001"}
{"timestamp":"2026-03-21T13:30:05+09:00","event":"codex_wrapper_finished","ticket_id":"worker-001","codex_cli_mode":"live","codex_session_record_path":"artifacts/codex/worker-001-run-0001-call-0001.json","returncode":0}
{"timestamp":"2026-03-21T13:30:06+09:00","event":"status_changed","ticket_id":"worker-001","before_status":"running","after_status":"review_pending"}
{"timestamp":"2026-03-21T13:30:07+09:00","event":"run_finished","ticket_id":"worker-001","run_id":"run-0001"}
```

---

## 9. Codex Session Record File Format

## 9.1 保存先

```text
artifacts/codex/<ticket_id>-<run_id>-<codex_call_id>.json
```

同一 `run_id` で複数回 wrapper を呼ぶ場合に備え、`codex_call_id` を含める。

---

## 9.2 用途

* live 実行の request / response を記録する
* stub 実行では caller から明示指定された再生元としてそのまま利用する
* stub 実行時にも、現在 run 用の session record を新規生成してよい
* 実行監査と回帰テストの両方に使えるようにする

---

## 9.3 必須フィールド

少なくとも以下を含める。

* `schema_version`
* `ticket_id`
* `plan_id`
* `run_id`
* `codex_call_id`
* `created_at`
* `codex_cli_mode`
* `request`
* `result`

live 実行で作られた record では、さらに以下を含めることが望ましい。

* `replayable`
* `recorded_from: "live"`

stub 実行で作られた record では、さらに以下を含めることが望ましい。

* `replayed_from`
* `recorded_from: "stub"`

---

## 9.4 `request` オブジェクトの推奨フィールド

* `argv`
* `cwd`
* `prompt_text`
* `input_files`
* `model`
* `reasoning_effort`
* `timeout_sec`

秘密情報を含みうる環境変数を丸ごと保存してはならない。
必要な場合は allowlist 化した `env` のみ保存してよい。

---

## 9.5 `result` オブジェクトの推奨フィールド

* `returncode`
* `stdout`
* `stderr`
* `last_message_text`
* `last_message_path`
* `stop_reason`
* `generated_artifacts`

stub で再生に使うには、少なくとも `returncode`, `stdout`, `stderr`, `last_message_text` が欠落していてはならない。

---

## 9.6 例

```json
{
  "schema_version": "1",
  "ticket_id": "worker-001",
  "plan_id": "plan-20260321-001",
  "run_id": "run-0001",
  "codex_call_id": "call-0001",
  "created_at": "2026-03-21T13:30:05+09:00",
  "codex_cli_mode": "live",
  "recorded_from": "live",
  "replayable": true,
  "request": {
    "argv": ["codex", "exec", "--output-last-message", "artifacts/messages/worker-001-run-0001.txt"],
    "cwd": "/repo",
    "prompt_text": "worker-001 を実行せよ",
    "model": "gpt-5.1-codex-mini",
    "reasoning_effort": "medium",
    "timeout_sec": 1800
  },
  "result": {
    "returncode": 0,
    "stdout": "updated 3 files",
    "stderr": "",
    "last_message_text": "実装が完了しました。",
    "last_message_path": "artifacts/messages/worker-001-run-0001.txt",
    "stop_reason": "completed",
    "generated_artifacts": [
      "src/cli.py",
      "tests/test_cli.py"
    ]
  }
}
```

---

## 9.7 stub 転用ルール

live で生成した record は、形式変換なしで stub の入力に使えることを要求する。
stub 側は caller から明示指定された path の record だけを読み、探索や自動推定は行わない。
ただし stub 実行側で以下を追加してもよい。

* 現在の run 用 `last_message_path` への再配置
* `replayed_from` の付与
* 現在 run 用 session record の再保存

元 record 自体を書き換えることは推奨しない。

---

## 10. Last Message File Format

## 10.1 保存先

```text
artifacts/messages/<ticket_id>-<run_id>.txt
```

---

## 10.2 用途

* `codex exec --output-last-message` の出力を保存する
* stub 実行時は replay した `last_message_text` を保存してよい
* JSONL ログとは混在させない
* 人間確認や後続レビューで参照可能にする

---

## 10.3 形式

* プレーンテキストとする
* JSONL に埋め込まない
* 生の最終メッセージを保存してよい

---

## 11. 読み書き時のバリデーション方針

## 11.1 Plan file

最低限以下を確認する。

* ファイルが存在すること
* YAML front matter が読めること
* `plan_id` があること
* `status` が許可値であること
* 必須セクション見出しが存在すること

## 11.2 Ticket file

最低限以下を確認する。

* ファイルが存在すること
* YAML front matter が読めること
* `ticket_id` があること
* `ticket_type` が許可値であること
* `status` が許可値であること
* `Dependencies` が読めること
* `Acceptance Criteria` が存在すること

## 11.3 Review result file

最低限以下を確認する。

* 対象 `ticket_id` が分かること
* 判定結果または判定不能理由が分かること

## 11.4 Log file

最低限以下を確認する。

* 各行が JSON として読めること
* `timestamp`, `event`, `ticket_id` が存在すること

## 11.5 Codex session record file

最低限以下を確認する。

* JSON として読めること
* `schema_version` があること
* `ticket_id`, `run_id`, `codex_call_id` があること
* `codex_cli_mode` が `live` または `stub` であること
* `request` と `result` があること
* stub 転用時に必要な result フィールドがあること

---

## 12. 禁止事項

* JSONL ログと最終メッセージを同一ファイルへ混在させてはならない
* `ticket_id` や `plan_id` の重複を許してはならない
* 必須メタデータ欠落のまま保存完了扱いにしてはならない
* 実行失敗時にログ保存を省略してはならない
* 判定不能時に理由を残さず review 結果を確定してはならない
* replay 不可能な live record を黙って stub 用とみなしてはならない
* 秘密情報を無加工で session record に保存してはならない

---

## 13. MVP 制約

現時点の最小実装では以下を許容する。

* Plan / Ticket の本文は厳密な構文解析ではなく見出し存在確認でもよい
* Review result file の詳細スキーマはまだ緩くてよい
* `generated_artifacts` など一部フィールドは省略可能
* `stdout`, `stderr` は巨大な場合に切り詰めてもよいが、その事実を明示すること
* `request` の diff 判定は未実装でもよい
* stub replay source は明示 path 指定のみをサポートすればよい

---

## 14. 将来拡張

* YAML front matter の厳密 JSON Schema 化
* Ticket / Review result の専用シリアライズ形式導入
* 添付成果物メタデータファイルの追加
* 実行ログのローテーションや圧縮
* 監査向けイベント種別の拡張
* session record の匿名化・正規化パイプライン

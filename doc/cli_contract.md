# `ticket_guys_b_team` CLI Contract

## 1. 文書の目的

本書は `ticket_guys_b_team` の CLI 契約を定義する。
対象は以下とする。

* CLI の責務
* エントリポイント
* コマンド体系
* 各コマンドの入力、出力、前提条件、失敗条件
* MVP の制約

本書は CLI 利用者および CLI 実装者向けの契約文書であり、詳細なファイル形式や状態遷移そのものは別文書を参照する。
Codex の live / stub 切り替えの詳細は `codex_cli_wrapper.md` を参照する。

---

## 2. 基本方針

* 人間が触る主要インターフェースは CLI とする
* CLI は内部フレームワーク概念を隠蔽し、業務概念を提供する
* 人間は Plan、Ticket、Review、Artifacts という概念で操作できるべきである
* 内部のエージェント実行基盤やワークフローエンジンの詳細は CLI から直接露出しない
* Codex 呼び出しは wrapper 経由でのみ行う
* 失敗時も、原因と次に取るべき行動が短く理解できる出力を返す

---

## 3. エントリポイント

正規の CLI 名は `tgbt` とする。

起動導線として以下を提供する。

```text
bin/tgbt
```

利用者は `bin/` を `$PATH` に追加したうえで `tgbt` を実行する。

例:

```bash
tgbt plan "ここに要件を書く"
```

---

## 4. コマンド体系

CLI は最低限以下のコマンドを提供する。

* `tgbt plan`
* `tgbt approve`
* `tgbt ticket`
* `tgbt run`
* `tgbt review-queue`
* `tgbt artifacts`

`review queue` のような自然言語的表現は説明上の呼称とし、実際のコマンド名は `review-queue` に正規化する。

---

## 5. 共通契約

## 5.1 終了コード

* 正常終了時は 0 を返す
* 以下の異常系は非 0 を返す

  * 仕様不足
  * 承認不足
  * 依存未解決
  * 検証失敗
  * 実行失敗
  * 入力不正
  * stub record 指定不備

---

## 5.2 エラー出力方針

エラー表示は少なくとも以下を短く示す。

* 原因
* 影響範囲
* 次に取るべき行動

例:

```text
ERROR: --stub-record is required in stub mode
Impact: worker execution was not started
Next: rerun with --codex-cli-mode stub --stub-record <path>
```

---

## 5.3 永続化方針

* 成功時も失敗時も、可能な限り状態更新とログ保存を行う
* 実行時に起きた事実はログへ保存する
* worker 実行では codex session record を保存する
* ログ保存自体に失敗した場合も、その失敗を標準エラー等へ可能な限り残す

---

## 5.4 出力方針

* 人間向けの簡潔な標準出力を返す
* 機械処理向けには JSON 出力を将来拡張してよい
* MVP では人間可読性を優先するが、ログと成果物パスが追跡できることを維持する
* worker 実行では `codex_cli_mode` と session record path を返すことが望ましい

---

## 5.5 モード用語

本仕様で扱う実行モードは `codex_cli_mode` のみである。

### `codex_cli_mode`

worker ticket 内部で Codex をどう扱うかを表す。

* `live`
* `stub`

`run` は常に実行コマンドであり、dry-run / preflight / validate は現時点では提供しない。
必要になった場合は将来サブコマンドとして追加する。

---

## 6. `plan` コマンド

## 6.1 目的

人間要望から仕様書兼実行計画書の草案を生成または更新する。

---

## 6.2 入力

以下のいずれかを受け付ける。

* 自然言語要求
* 既存 `plan_id` と追記指示

例:

```bash
tgbt plan "CLI で plan / approve / ticket / run を扱えるようにしたい"
```

```bash
tgbt plan --plan-id plan-20260321-001 "差し戻し条件を追記する"
```

---

## 6.3 出力

* `artifacts/plans/<plan_id>.md` を生成または更新する
* 実行結果として少なくとも `plan_id` と保存先を表示する

例:

```text
Created: artifacts/plans/plan-20260321-001.md
Status: draft
```

---

## 6.4 状態遷移

* 新規生成時は `draft`
* 更新時も `draft`
* このコマンド単体では `approved` に遷移しない
* `approved` 済み計画を更新した場合も `draft` に戻す

---

## 6.5 失敗条件

* 出力先へ書き込めない
* 入力が空である
* 対象 `plan_id` が見つからない
* front matter 更新に失敗した

---

## 6.6 MVP 制約

* 必須セクションを並べたテンプレート草案生成に留める
* 要望内容の深い自動解釈や高度な要件抽出は未実装でよい

---

## 7. `approve` コマンド

## 7.1 目的

指定した Plan を `in_review` または `approved` に遷移させる。

---

## 7.2 入力

* `plan_id`
* 目標状態または操作種別

例:

```bash
tgbt approve plan-20260321-001 --to in_review
```

```bash
tgbt approve plan-20260321-001 --to approved
```

---

## 7.3 出力

* 更新後状態
* 不足がある場合は不足理由一覧

例:

```text
Plan: plan-20260321-001
Status: in_review
```

または

```text
Approval rejected
Missing:
- 検証戦略
- 差し戻し条件
```

---

## 7.4 遷移ルール

* レビュー開始操作では `in_review` へ遷移する
* 承認操作では `in_review` の計画のみ `approved` にできる
* `draft -> approved` は許可しない

---

## 7.5 承認前バリデーション

最低限以下を確認する。

* 必須項目が存在すること
* 未確定事項について、次フェーズ進行可否が明示されていること
* 差し戻し条件が空でないこと
* 検証戦略が空でないこと

---

## 7.6 失敗条件

* Plan file が存在しない
* 現在状態から要求遷移が許可されていない
* 必須項目が不足している

---

## 8. `ticket` コマンド

## 8.1 目的

`approved` の計画からチケット群を生成する。

---

## 8.2 入力

* `plan_id`

例:

```bash
tgbt ticket plan-20260321-001
```

---

## 8.3 出力

* root ticket 1 枚以上
* worker / review / integration ticket 群
* 各チケットファイル保存先

例:

```text
Generated tickets:
- artifacts/tickets/root-001.md
- artifacts/tickets/worker-001.md
- artifacts/tickets/review-001.md
- artifacts/tickets/integration-001.md
```

---

## 8.4 前提条件

* 対象 Plan が `approved` であること

---

## 8.5 生成ルール

* すべてのチケットに一意な `ticket_id` を付与する
* すべてのチケットに `Dependencies` を含める
* すべてのチケットに `Acceptance Criteria` を含める
* worker ticket は `default_codex_cli_mode` を持ってよい
* review ticket の依存先は対応 worker ticket の `review_pending`
* integration ticket の依存先は対象 review ticket の `done`

---

## 8.6 失敗条件

* Plan が存在しない
* Plan が `approved` でない
* 出力先へ書き込めない
* 必須セクション不足でチケット生成不能

---

## 8.7 MVP 制約

* 1 plan から `worker 1 + review 1 + integration 1 + root 1` の定型構成を生成してよい
* 作業分解の自動解析による複数 worker 分割は未実装でよい

---

## 9. `run` コマンド

## 9.1 目的

root ticket または個別 `ticket_id` を指定して実行する。

---

## 9.2 入力

* `ticket_id`
* 必要に応じて `--codex-cli-mode`
* 必要に応じて `--model`, `--reasoning-effort`
* 必要に応じて `--stub-record`

現在の想定形:

```bash
tgbt run <ticket_id> [--codex-cli-mode <live|stub>] [--stub-record <path>] [--model <model>] [--reasoning-effort <effort>]
```

ルール:

* `--codex-cli-mode` の既定値は `live`
* `--codex-cli-mode` は worker ticket 実行時に意味を持つ
* MVP では root ticket を起点にした `--codex-cli-mode stub` 実行はサポートしない
* `--stub-record` は `--codex-cli-mode stub` のとき必須である
* `--codex-cli-mode live` では `--stub-record` を指定してはならない

例:

```bash
tgbt run worker-001 --codex-cli-mode live
```

```bash
tgbt run worker-001 --codex-cli-mode stub --stub-record artifacts/codex/worker-001-run-0001-call-0001.json
```

```bash
tgbt run root-001 --codex-cli-mode live
```

---

## 9.3 出力

少なくとも以下を返す。

* 更新された Ticket 状態
* ログ保存先
* 生成・更新された成果物パス

worker 実行では、さらに以下を返すことが望ましい。

* `codex_cli_mode`
* `codex_session_record_path`
* `replayed_from` または `none`

例:

```text
Ticket: worker-001
Status: review_pending
CodexCliMode: stub
Log: artifacts/logs/worker-001-run-0002.jsonl
CodexSession: artifacts/codex/worker-001-run-0002-call-0001.json
ReplayedFrom: artifacts/codex/worker-001-run-0001-call-0001.json
Artifacts:
- artifacts/messages/worker-001-run-0002.txt
```

---

## 9.4 共通ルール

* root ticket 指定時は、依存関係に従って実行可能なチケットだけを開始する
* 依存未解決のチケットは開始してはならない
* `blocked` または `failed` が発生した場合は、影響範囲が分かる出力を返すことが望ましい
* 少なくとも開始、依存判定、wrapper 実行、受け入れゲート、状態更新、終了をログへ記録する
* worker 実行では Codex CLI wrapper を必ず経由する

---

## 9.5 `codex_cli_mode`

* worker ticket では Codex CLI wrapper を呼び出す
* `--codex-cli-mode live` では wrapper が `codex exec` を実行する
* `--codex-cli-mode stub` では wrapper が `--stub-record` で明示指定された record を再生する
* review / integration ticket では自動受け入れゲートを実行する
* 実行内容は常時ログへ保存する

---

## 9.6 失敗条件

* Ticket file が存在しない
* 対象 Plan が未承認である
* 依存条件が未解決である
* 外部実行に失敗した
* 自動受け入れゲートが fail した
* `--stub-record` が未指定である
* 指定された stub record が見つからない
* 指定された stub record の schema または内容が不正である
* root ticket に対して `--codex-cli-mode stub` を指定した
* 状態更新またはログ保存に失敗した

---

## 9.7 MVP 制約

* root ticket 実行時も並列実行は行わず逐次実行に留める
* 影響範囲分析や継続判断支援の詳細表示は未実装でもよい
* まずは JSON または簡潔テキストで結果を返せればよい
* stub replay source は `--stub-record` による明示 path 指定のみをサポートすればよい
* root ticket を起点にした stub 実行は未対応でよい

---

## 10. `review-queue` コマンド

## 10.1 目的

`review_pending` のチケット一覧を表示する。

---

## 10.2 入力

* 任意で `plan_id`
* 任意で `priority` や絞り込み条件を将来追加してよい

例:

```bash
tgbt review-queue
```

---

## 10.3 出力

一覧には最低限以下を含める。

* `ticket_id`
* `ticket_type`
* `status`
* `priority`
* `dependencies`

例:

```text
worker-001  worker  review_pending  high  depends: review-001(pass pending)
```

または review ticket の待機一覧として実装してもよいが、用語の定義は一貫させること。

---

## 10.4 失敗条件

* Ticket directory が存在しない
* チケット読み込みに失敗した

---

## 11. `artifacts` コマンド

## 11.1 目的

指定した `plan_id` または `ticket_id` に紐づく成果物パスを表示する。

---

## 11.2 入力

* `plan_id` または `ticket_id`

例:

```bash
tgbt artifacts --plan-id plan-20260321-001
```

```bash
tgbt artifacts --ticket-id worker-001
```

---

## 11.3 出力

以下を対象に含める。

* 生成・更新された成果物
* review result file
* 実行ログ
* codex session record file
* last message file

存在しない成果物は存在しないことを明示する。

例:

```text
Artifacts for worker-001:
- artifacts/tickets/worker-001.md
- artifacts/logs/worker-001-run-0001.jsonl
- artifacts/codex/worker-001-run-0001-call-0001.json
- artifacts/messages/worker-001-run-0001.txt
- artifacts/reviews/review-001.md
Missing:
- artifacts/output/worker-001-result.json
```

---

## 11.4 失敗条件

* 対象識別子が存在しない
* 紐付け情報が解決できない

---

## 12. 実装依存事項

CLI 実装は以下を前提とする。

* Python 3.12
* `.venv`
* `typer`
* `langgraph`
* 型ヒント、docstring、pytest、pyright
* `pip install -e .` で導入可能であること

---

## 13. バックエンド依存事項

* ワークフロー制御には `LangGraph` を用いる
* worker 実行は `CodexCliWrapper` 経由で行う
* live モードでは `codex exec` を用いる
* stub モードでは record replay を用いる
* 本番 smoke test は opt-in とする
* トークン消費抑制のため、既定候補モデルとして `gpt-5.1-codex-mini` を用いてよい

これらは CLI の外側にある実装詳細だが、CLI の振る舞いに影響するため契約上の前提として記録する。

---

## 14. 禁止事項

* 未承認 Plan から `ticket` や `run` を開始してはならない
* 完了条件が曖昧な Ticket を実行してはならない
* 自動受け入れゲートなしで大量実行してはならない
* 下流工程を人間の全件レビュー前提で設計してはならない
* CLI から `codex exec` を直接叩いてはならない
* stub モードで live 相当の副作用が発生したように偽装してはならない

---

## 15. MVP と理想仕様の差分

現時点の最小実装では以下を許容する。

* `plan` はテンプレート草案生成中心でよい
* `ticket` は定型 4 枚構成でよい
* `run` は逐次実行のみでよい
* review / integration の受け入れゲートは `pytest -q` 優先、`tests/` 不在時は軽量判定でよい
* `pyright` 自動実行は未実装でもよい
* 影響範囲分析や継続判断支援は簡易出力でもよい
* stub では `--stub-record` による明示 replay のみをサポートすればよい

---

## 16. 将来拡張

* JSON 出力モード
* 並列実行制御オプション
* review queue の高度フィルタ
* 複数リポジトリ対応
* Web UI との併用
* record から fixture への昇格コマンド

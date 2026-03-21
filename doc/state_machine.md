# `ticket_guys_b_team` State Machine Specification

## 1. 文書の目的

本書は `ticket_guys_b_team` における状態遷移仕様を定義する。
対象は以下の 2 系統である。

* Plan の状態遷移
* Ticket の状態遷移

本書は状態遷移の定義に集中し、CLI 契約、ファイル形式、製品背景説明は扱わない。

---

## 2. 設計原則

* 状態遷移は明示的でなければならない
* 状態ごとの実行可否条件を機械的に判定できなければならない
* 未承認計画や未解決依存のまま実行を開始してはならない
* 状態遷移の結果は常に永続化され、ログで追跡可能でなければならない
* 失敗時も途中状態と停止理由を可能な限り保存しなければならない

---

## 3. Plan State Machine

## 3.1 状態一覧

Plan は以下の状態を持つ。

* `draft`
* `in_review`
* `approved`

---

## 3.2 状態の意味

### `draft`

計画草案の状態。

* 新規生成直後の既定状態である
* 既存計画を編集した直後の状態である
* 人間レビュー前提の未承認状態である
* この状態からチケット生成や実装実行を開始してはならない

### `in_review`

人間レビュー中の状態。

* 人間が計画内容を確認している状態である
* 必要に応じて差し戻しや修正を行う
* この状態からのみ `approved` へ遷移できる

### `approved`

後続フェーズ進行が許可された状態。

* チケット生成の唯一の許可状態である
* 実装実行の唯一の許可状態である
* 再編集された場合は `draft` へ戻る

---

## 3.3 許可される遷移

* `draft -> in_review`
* `in_review -> approved`
* `approved -> draft`
* `in_review -> draft`

`draft -> approved` は許可しない。

---

## 3.4 遷移ルール

### `draft -> in_review`

レビュー開始操作によって遷移する。

前提条件:

* 計画ファイルが存在すること
* 必須セクションが最低限存在することが望ましい

備考:

* この時点では内容不備が残っていてもよい
* ただしレビュー対象として成立しないほど欠落している場合は CLI 側で警告または失敗としてよい

### `in_review -> approved`

承認操作によって遷移する。

前提条件:

* 必須項目が存在すること
* 未確定事項について、次フェーズへ進める範囲と進められない範囲が明示されていること
* 差し戻し条件が空でないこと
* 検証戦略が空でないこと

失敗時:

* 状態は `in_review` に留まる
* 不足理由を表示する

### `approved -> draft`

再編集操作によって遷移する。

前提条件:

* 承認済み計画に変更が加えられたこと

意味:

* 承認済み内容の固定が破られたため、再レビューが必要になる

### `in_review -> draft`

レビュー差し戻し、または AI による修正再開によって遷移する。

意味:

* 再度草案状態へ戻し、修正を前提に扱う

---

## 3.5 禁止ルール

* `approved` でない Plan からチケット生成を開始してはならない
* `approved` でない Plan からチケット実行を開始してはならない
* 承認条件未達のまま `approved` に遷移してはならない

---

## 4. Ticket State Machine

## 4.1 状態一覧

Ticket は以下の状態を持つ。

* `todo`
* `blocked`
* `running`
* `review_pending`
* `done`
* `failed`

---

## 4.2 状態の意味

### `todo`

未着手状態。

* 作成済みだがまだ開始していない
* 依存が未解決でもよい
* 開始可否の判定前である

### `blocked`

停止状態。

* 仕様不足
* 依存未完了
* 人間判断待ち
* 権限不足
* 判定不能

などにより進行できない状態を表す。

### `running`

実行中状態。

* 実行主体が現在このチケットの処理を進めている
* 実行ログを継続的に残す対象状態である

### `review_pending`

レビュー待ち状態。

* worker ticket が実装とローカル検証を終えた後の待機状態である
* review ticket または後続確認の入力として扱う

### `done`

完了状態。

* 完了条件を満たし、後続依存から参照可能である

### `failed`

失敗状態。

* 自動受け入れゲート失敗
* 外部実行失敗
* 中断
* review fail

などを表す。

---

## 4.3 共通遷移ルール

* 依存条件を満たすまでは `running` へ遷移してはならない
* `done` と `failed` は終端状態として扱う
* `blocked` は停止理由付きの待機状態として扱う
* 停止理由が解消された場合のみ `todo` または `running` に戻せる
* 状態遷移時は前後状態と理由をログへ記録しなければならない

---

## 5. Ticket Dependency Model

各依存関係は以下の組で表現する。

* `ticket_id`
* `required_state`

例:

* worker A が worker B の完了を待つ: `ticket_id=B, required_state=done`
* review R が worker W のレビュー待ちを待つ: `ticket_id=W, required_state=review_pending`
* integration I が review R の完了を待つ: `ticket_id=R, required_state=done`

依存条件を満たさない場合、開始操作は失敗または `blocked` とする。

---

## 6. Ticket Type 別状態規則

## 6.1 root ticket

### 役割

* Plan 全体の実行統制
* 配下チケット一覧の保持
* 依存グラフと実行順序ルールの保持

### 遷移

* `todo -> running`
* `running -> blocked`
* `running -> failed`
* `running -> done`

### `done` 条件

* 配下の必須チケットがすべて `done` であること

### `failed` 条件

* 実行継続不能な失敗が発生し、root として失敗確定した場合

### `blocked` 条件

* 配下に `blocked` が存在し、継続判断が必要な場合
* 人間判断待ち論点が存在する場合

---

## 6.2 worker ticket

### 役割

* 個別成果物の生成または変更
* ローカル検証の実施

### 基本遷移

* `todo -> running`
* `running -> review_pending`
* `running -> blocked`
* `running -> failed`
* `review_pending -> done`
* `review_pending -> failed`

### `todo -> running`

前提条件:

* すべての依存条件が満たされていること
* 参照入力が存在すること

### `running -> review_pending`

前提条件:

* 実装が完了していること
* ローカル検証が完了していること
* Outputs が保存されていること

### `running -> blocked`

条件例:

* 仕様不足
* 依存解決不能
* 必要入力不足
* 人間判断待ち

### `running -> failed`

条件例:

* 外部実行失敗
* 受け入れ前提のローカル検証失敗
* 中断

### `review_pending -> done`

前提条件:

* 対応する review ticket が `done`
* review 判定結果が `pass`

### `review_pending -> failed`

前提条件:

* 対応する review ticket が `failed`
* review 判定結果が `fail`

備考:

* worker ticket 単独では `done` へ直接遷移しない
* review 結果によって最終確定する

---

## 6.3 review ticket

### 役割

* 対象 worker ticket の成果物検証
* Acceptance Criteria の妥当性確認
* レビュー結果ファイルの生成

### 基本遷移

* `todo -> running`
* `running -> blocked`
* `running -> done`
* `running -> failed`

### `todo -> running`

前提条件:

* 対象 worker ticket が `review_pending`
* 対象成果物が存在すること

### `running -> done`

前提条件:

* レビュー結果ファイルを書き出したこと
* 判定結果が `pass`

副作用:

* 対象 worker ticket を `done` に更新する

### `running -> failed`

前提条件:

* レビュー結果ファイルを書き出したこと
* 判定結果が `fail`

副作用:

* 対象 worker ticket を `failed` に更新する

### `running -> blocked`

条件例:

* 対象 worker が `review_pending` に達していない
* 対象成果物が不足している
* 判定不能
* 仕様不足

要件:

* 理由をレビュー結果ファイルへ記録する

---

## 6.4 integration ticket

### 役割

* 複数成果物の統合
* 統合後の検証
* 統合レビュー結果ファイルの生成

### 基本遷移

* `todo -> running`
* `running -> blocked`
* `running -> done`
* `running -> failed`

### `todo -> running`

前提条件:

* 依存対象 review ticket がすべて `done`
* 統合対象成果物が参照可能であること

### `running -> done`

前提条件:

* 統合レビュー結果ファイルを書き出したこと
* 統合検証が pass したこと

### `running -> failed`

前提条件:

* 統合レビュー結果ファイルを書き出したこと
* 統合検証が fail したこと

### `running -> blocked`

条件例:

* 必要成果物不足
* 統合前提未成立
* 判定不能
* 人間判断待ち

---

## 7. 状態遷移時の必須記録

すべての状態遷移について、少なくとも以下をログに残す。

* `timestamp`
* `ticket_id`
* `event`
* `before_status`
* `after_status`
* `reason`

必要に応じて以下も残す。

* `plan_id`
* `ticket_type`
* `run_id`
* `dependency_check_result`
* `related_ticket_ids`

---

## 8. 判定原則

* 実行可否は現在状態と依存状態から機械的に判定する
* review の pass / fail はレビュー結果ファイルにより確定する
* integration の pass / fail は統合レビュー結果ファイルにより確定する
* 判定不能時は黙って進めず `blocked` に遷移する

---

## 9. 禁止事項

* `approved` でない Plan を起点に Ticket 実行を開始してはならない
* 依存未解決の Ticket を `running` にしてはならない
* worker ticket を review を経ずに `done` にしてはならない
* review 結果未確定のまま integration を開始してはならない
* 停止理由を記録せずに `blocked` にしてはならない
* ログを残さずに状態遷移してはならない

---

## 10. MVP 制約

現時点の最小実装では以下を許容する。

* root ticket 実行は一般化スケジューラではなく逐次評価でよい
* integration ticket は単一 review ticket を対象とする定型構成でもよい
* `blocked` 理由の構造化は粗くてもよいが、少なくとも人間が読める説明を残すこと

---

## 11. 将来拡張

* 再実行専用状態の導入
* cancel / aborted の区別
* partial_success の導入
* 並列スケジューリング対応状態の追加
* 人間レビュータスク専用状態の追加

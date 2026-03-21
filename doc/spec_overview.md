# `ticket_guys_b_team` Specification Overview

## 1. 文書の目的

本書は `ticket_guys_b_team` の仕様群に対する入口文書である。

`ticket_guys_b_team` は、**仕様レビュー駆動のマルチエージェント開発**を、人間が扱いやすい業務概念で運用するための CLI フロントエンドである。

本プロダクトの主目的は、エージェントそのものの賢さを追求することではなく、以下を扱いやすくすることである。

* 人間要望からの仕様化
* 仕様レビューと承認
* チケット分解
* 実行統制
* 自動受け入れゲート中心の運用

本書自体は詳細仕様を網羅しない。詳細は各分割文書を参照する。

---

## 2. 現在の仕様文書構成

現在、一次参照先として扱う仕様文書は以下の 4 本である。

* `product-vision.md`
* `state-machine.md`
* `file-format.md`
* `cli-contract.md`

本書はそれらへの入口として機能する。

---

## 3. 仕様文書の読み方

最初に本書で全体像を確認し、その後は関心に応じて以下の文書を参照する。

### 3.1 プロダクト背景と設計思想

* `product-vision.md`

用途:

* プロダクトの背景
* 解決したい問題
* 基本思想
* 人間と AI の役割分担
* 初期バージョンで重視する価値
* MVP における割り切り

読むべき場面:

* なぜこの設計にしているのか知りたいとき
* 実装方針の背景を確認したいとき
* 新規参加者へプロダクトの意図を共有したいとき

### 3.2 状態遷移仕様

* `state-machine.md`

用途:

* Plan の状態遷移
* Ticket の状態遷移
* ticket type ごとの遷移規則
* 依存条件と開始条件
* `blocked` / `failed` / `review_pending` の扱い

読むべき場面:

* 状態管理コードを実装するとき
* 遷移バリデーションを書くとき
* run 時の可否判定を整理するとき

### 3.3 ファイル形式仕様

* `file-format.md`

用途:

* Plan file format
* Ticket file format
* Review result file format
* Execution log JSONL format
* Last message file format
* ディレクトリ構造と命名規則

読むべき場面:

* 永続化層を実装するとき
* front matter の schema を揃えるとき
* ログフォーマットや artifact path を決めるとき

### 3.4 CLI 契約

* `cli-contract.md`

用途:

* CLI の責務
* エントリポイント
* コマンド体系
* 各コマンドの入力、出力、前提条件、失敗条件
* MVP で許容する制約

読むべき場面:

* Typer ベースの CLI を実装するとき
* コマンド引数や終了コードを整理するとき
* ユーザー向け CLI 振る舞いを固定したいとき

---

## 4. 実装者向けの推奨参照順

### 4.1 CLI から先に作る場合

1. `cli-contract.md`
2. `state-machine.md`
3. `file-format.md`
4. 必要に応じて `product-vision.md`

### 4.2 永続化層から先に作る場合

1. `file-format.md`
2. `state-machine.md`
3. `cli-contract.md`
4. 必要に応じて `product-vision.md`

### 4.3 実行オーケストレーションから先に作る場合

1. `state-machine.md`
2. `cli-contract.md`
3. `file-format.md`
4. 必要に応じて `product-vision.md`

---

## 5. 文書ごとの責務分離

各文書の責務は重複させすぎないことを原則とする。

* 本書は入口と参照案内のみを担う
* `product-vision.md` は背景・目的・設計思想を担う
* `state-machine.md` は状態遷移だけを担う
* `file-format.md` はファイル形式だけを担う
* `cli-contract.md` は CLI 契約だけを担う

実装判断が必要な場合、まず分割文書を参照し、背景や意図の確認が必要な場合のみ `product-vision.md` を参照する。

---

## 6. 現時点の推奨運用

* 日常的な実装では、本書を入口として使う
* 実装の一次参照先は分割文書とする
* `product-vision.md` は背景確認用として扱う
* 仕様の追加や修正は、まず責務に対応する分割文書へ反映する
* 本書には詳細仕様を書き戻しすぎない

---

## 7. 今後の整理方針

将来的には以下の形へさらに寄せることを推奨する。

* 本書を正式な index document として維持する
* 分割文書を実装の一次参照先として固定する
* 必要なら `architecture.md` や `domain-model.md` を追加し、責務をさらに分離する
* overview 文書は薄く保ち、詳細を抱え込まないようにする

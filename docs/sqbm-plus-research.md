# 東芝 SQBM+ 調査メモ（qplib ソルバー中心）

- 調査日: 2026-11-11
- 主な一次情報:
  - 『User's Manual for SQBM+ V2』（On-premises 版, A3 edition, 2024-08-05, サーバ版数 2.0.3）
  - 『User's Manual for SQBM+ for AWS V2』（v2.1 系, tsp/shift/qap 章を含む）
  - 『SQBM+ for AWS Release Notes』（〜v2.1.3）
- 本文は上記資料を要約したもの。「要検証」と付けた項目は資料から推測したもので、実機で確認していない。

---

## 1. 概要

| 項目 | 内容 |
|---|---|
| 正式名 | SQBM+（Simulated Quantum-inspired Bifurcation Machine plus） |
| 提供元 | 東芝デジタルソリューションズ |
| 基盤技術 | シミュレーテッド分岐（SB）アルゴリズム。Goto, Tatsumura & Dixon (2019, *Sci. Adv.* 5(4)) と、bSB/dSB を提案した Goto et al. (2021, *Sci. Adv.* 7(6)) |
| 計算資源 | GPU（最低 16GB の GPU メモリ。大規模問題では 1 GPU あたり 32GB 以上を推奨） |
| 解の性質 | 近似解（良解）探索。最適性の保証はない |
| インタフェース | REST API（ステートレスで、リクエストやレスポンスのデータはサーバに残らない） |
| 提供形態 | AWS Marketplace AMI（SQBM+ for AWS）、Azure Marketplace、オンプレミス（VM イメージ / RPM）、パートナー経由（Fixstars Amplify、Strangeworks） |

## 2. バージョン履歴

| 版 | 時期 | 主な内容 |
|---|---|---|
| v1.6.2 | 〜2023 | ising / autoising ソルバー、QP ソルバー。変数は最大 10 万 |
| v2.0.1 | 2023-11-27 | **qubo / qplib / pubo** ソルバーを新設。QP ソルバーは廃止され qplib ソルバーが後継になった。変数上限が 1,000 万に拡大。SB2.5 / SB3.0 アルゴリズム追加。課金が計算時間ベースに変更 |
| v2.0.3 | 2024-08 | オンプレミス版マニュアルの記載版 |
| v2.1.0 | 2024-08-22 | **tsp / shift / qap** ソルバー（目的別ソルバー）を追加。qplib に `detail_level` / `detail_log` を追加（解なし時の詳細情報） |
| v2.1.1〜2.1.3 | 2025-04〜07 | AWS インスタンス種別の追加・削除（p5.48xlarge、g6e 系の追加、p3 系の一部削除）と IMDSv2 対応 |
| v2.2 | 2026-06-25 発表 | 10 億変数の QUBO に対応。GPU リソースの柔軟な割り当て、SchemaSBM（候補解のパターンから探索空間を絞り込むアルゴリズム）を追加。オンプレミス GPU サーバ向けと、パートナー向けモジュール（AMI）として提供。**qplib ソルバーの仕様が変わったかどうかは公開情報からは確認できない** |

## 3. ソルバー一覧（v2.1 時点）

| ソルバー | 問題 | 変数 | 制約 | 主な上限 |
|---|---|---|---|---|
| qubo | QUBO | バイナリ | なし | 変数 1,000 万 |
| **qplib** | 線形制約付き二次計画 | **バイナリ / 連続（混在可）** | **線形（等式・不等式）** | 変数 1,000 万、制約 100 万 |
| pubo | 最大 4 次の多項式 | バイナリ / 連続 | なし | 変数 10 万 |
| tsp | 巡回セールスマン（TSPLIB 形式） | — | — | — |
| shift | シフトスケジューリング（JSON） | — | 制約はコスト（重み付き）として扱う | 日数 1,080、ジョブ 3,000、従業員 3,000 |
| qap | 二次割当問題（qplib 形式） | — | — | — |

---

## 4. qplib ソルバー詳細

### 4.1 問題定義

```
minimize    (1/2) xᵀ Q x + B·x
subject to  LHS ≤ A x ≤ RHS
            x_i ∈ {0,1}  または  x_i ∈ ℝ（上下限付き）
```

- Q は二次の係数行列（QUBO 行列）、B は一次の係数ベクトル、A は M×N の制約行列（M は制約数、N は変数数）。
- 制約の各行は次の 4 種類のいずれか。
  - 上下限付きの不等式: LHS_m < RHS_m
  - 下限のみ: RHS_m = +inf
  - 上限のみ: LHS_m = −inf
  - 等式: LHS_m = RHS_m
- 係数の絶対値は 1e+20 以下にする（超える場合は、制約を保ったままスケーリングする）。
- **整数変数は扱えない**（変数型は 0 = 連続、1 = バイナリのみ）。Amplify の対応表でも、Qplib の整数変数の欄は「-」（非対応）になっている。

### 4.2 リクエスト

```
POST http://{host}:8000/solver/qplib?{query}
Content-Type: application/octet-stream
Body: qplib 形式テキスト または HDF5 バイナリ（形式は自動判別）
```

- 問題ファイルをリクエストボディに入れる代わりに、ヘッダで参照先を渡すこともできる。
  - `X-Input-Data-URI`: サーバから参照できる絶対パス
  - `Content-Location`: HTTPS 上の URL（S3 など）
- `GET /healthcheck` は `{"status":"pass"}` か `fail` を返す。`GET /version` は `{"version":"2.0.3"}` のような版数を返す。

### 4.3 qplib 形式（東芝方言）

標準 QPLIB（ZIB）と似たタグ形式だが、**サブセットかつ独自解釈を含む**。Strangeworks のドキュメントも「ZIB の標準ファイルはそのままでは通らない可能性がある」と注意している。

**ヘッダ 3 行**

1. 問題名: `QPLIB_` で始まる文字列
2. 問題タイプ（3 文字。目的・変数・制約の順）:
   - qplib ソルバー: `QBB`, `QBL`, `QCB`, `QCL`, `QGB`, `QGL`
   - pubo ソルバー: `QBB`, `QCB`, `QGB`
   - 1 文字目（目的）は Q のみ。
   - 2 文字目（変数）は B = 全バイナリ、C = 全連続、G = 混在。
     - 標準 QPLIB の G は「一般整数を含む混在」を意味するので、ここでの意味とは違う。
   - 3 文字目（制約）は B = 線形制約なし（変数の上下限のみ）、L = 線形制約あり。
3. 目的の向き: `minimize` または `maximize`

**本体タグ**（1 行目に件数か値を書き、行末に `# タグ名` を付ける。件数を指定するタグでは、その下にデータ行を件数分続ける）

| タグ | 内容 | データ行 |
|---|---|---|
| number of variables | 変数数（2〜10,000,000） | — |
| number of constraints | 制約数（0〜1,000,000）。制約タイプ B のときは 0 以外だとエラー | — |
| default left-hand-side value | LHS の既定値 | — |
| default right-hand-side value | RHS の既定値 | — |
| default value for linear coefficients in objective | B の既定値 | — |
| default variable type | 変数型の既定値（0 = 連続、1 = バイナリ）。変数タイプ B / C のときは書かない | — |
| default variable upper bound value | 変数上限の既定値。変数タイプ B のときは書かない | — |
| default variable lower bound value | 変数下限の既定値。変数タイプ B のときは書かない | — |
| number of quadratic terms in objective | Q の非ゼロ数（**1 以上**、上限 1 億） | `i j 値`（i ≥ j の下三角） |
| number of pubo terms in objective | 3 次以上の項（pubo のみ） | `i j k (l) 値` |
| number of non-default linear coefficients in objective | B の上書き | `i 値` |
| number of linear terms in all constraints | A の非ゼロ数 | `制約番号 変数番号 値` |
| number of non-default left-hand-sides | LHS の上書き | `制約番号 値` |
| number of non-default right-hand-sides | RHS の上書き | `制約番号 値` |
| number of non-default variable upper bounds | 変数上限の上書き | `i 値` |
| number of non-default variable lower bounds | 変数下限の上書き | `i 値` |
| number of non-default variable types | 変数型の上書き（変数タイプ G のとき） | `i 型` |

**注意点（実装時に要確認）**

- インデックスは **1 始まり**。
- 無限大は qplib テキストでは `1.79769313486232e+308`、HDF5 では `3.40283e+38` と書く。
- A・LHS・RHS のデータ行について、マニュアルの説明文は「variable index」と書いているが、例（制約 1 本のナップサック: `1 1 2`, `1 2 3`, …）からは **1 列目が制約番号** と読める。
- **目的関数の 1/2 係数**: マニュアルのナップサック例では、対角に −22, −26, −34, −38 を置いた問題で、全 1 の解の評価値が −60 になっている。これは 1/2·(−120) なので、**対角項には 1/2 が掛かる**。
  - 非対角項 `i j v` が v·x_i·x_j と解釈されるのか、v/2·x_i·x_j と解釈されるのかは要実機検証。
  - マニュアル付属の HDF5 変換スクリプトは Q を対称化してから下三角に畳み込んでおり、標準 QPLIB と同じく v·x_i·x_j と解釈されると推測できる。
- 標準 QPLIB にある `objective constant`、`infinity value`、二次制約、初期点、変数名・制約名といったタグは記載がない → **定数項はクライアント側で別途加算する**。
- 二次項の件数は「1 以上」と書かれているので、純線形の目的関数でも二次項が 1 つ以上必要な可能性がある（要検証）。バイナリなら x² = x なので、線形項を対角に置けば代用できる。
- 制約のない問題（タイプ B）では LHS / RHS 系のタグを書かない。

**最小例**（自作。マニュアルの knapsack 例と同じ構造）

```
QPLIB_example
QBL
minimize
3 # number of variables
1 # number of constraints
-1.79769313486232e+308 # default left-hand-side value
1 # default right-hand-side value
0 # default value for linear coefficients in objective
1 # number of quadratic terms in objective
2 1 1.5
3 # number of non-default linear coefficients in objective
1 -1
2 -1
3 -1
3 # number of linear terms in all constraints
1 1 1
1 2 1
1 3 1
```

（変数 3 個で、「高々 1 個を選ぶ」制約のもと −Σx + 1.5·x1·x2 を最小化する例。ただし、非対角項が v·x_i·x_j と解釈される場合に限る）

- マニュアルは「タグ指定で情報を設定する形式」と説明しており、行末の `# タグ名` でフィールドを識別しているように見える。
  - ただし、タグの順序を入れ替えてよいかどうかは不明。
  - マニュアルの 2 つの例（knapsack と max3sat）で順序が一致しているので、それに合わせるのが無難。順序は「既定値系 → 目的二次項 → (pubo 項) → 目的一次項の上書き → 制約行列 → LHS/RHS の上書き → 変数の上下限・型の上書き」。

### 4.4 HDF5 形式

| パス | 内容 | 属性 `format` |
|---|---|---|
| `/qubo` | Q（`data` / `indptr` / `indices`。CSR または dense） | `csr` / `dense` |
| `/linear` | B ベクトル | `dense` |
| `/constraints/coeff` | A 行列 | `csr` / `dense` |
| `/constraints/lower` | LHS ベクトル | `dense` |
| `/constraints/upper` | RHS ベクトル | `dense` |

- データ型は data が float32、indices / indptr が uint32。ファイルは 2GB 未満にする。
- **qplib テキストより大きな非ゼロ数を扱える**（Q が疎なら 5 億、dense なら 8 億）。
- Amplify は常に HDF5 で送信する。
- 大きな HDF5 を連続して送ると 400 エラーになることがあるので、リクエストの間隔を空ける（v2.1 マニュアルの注記）。

### 4.5 パラメータ（クエリ文字列で指定）

**全ソルバー共通**

| 名前 | 既定 | 内容 |
|---|---|---|
| steps | 0（自動） | 1 解あたりの SB 更新ステップ数（0〜1 億） |
| loops | 0（= 1 億） | 解探索の反復数。最低でも loops × GPU 数 × SM 数 個の解を探索する |
| timeout | 10 秒 | 計算時間の上限。**AWS 版ではこの値が課金時間になる**。システム設定 `timeout_upper_bound`（既定 3600 秒）で頭打ちになる |
| maxwait | 60 秒 | キューでの最大待ち時間（超えると 504） |
| target | なし | 目的値がこの値に達したら停止 |
| maxout | 1 | 返す解の最大数（良い順） |

**qubo 系（qplib でも使える）**

| 名前 | 既定 | 内容 |
|---|---|---|
| algo | 0（複数を自動で試す） | 15 = bSB、20 = dSB、25 / 30 = 局所解から脱出しやすい拡張版。末尾 1 = C の自動調整、末尾 4 = 係数のオートスケール、末尾 5 = その両方（151, 154, 155, 201, 204, 205, 251〜255, 301〜305） |
| algos | — | 正規表現で複数のアルゴリズムを指定 |
| dt | 0（自動） | 時間刻み（0.0〜1.5） |
| C | 0（自動） | 論文中の ξ0 に相当する定数 |
| blocks | 0（自動） | GPU ブロック数（0〜40） |
| multishot | 0（自動） | 同じパラメータで初期値だけ変えた解の数（0〜10） |

**qplib 固有**

| 名前 | 既定 | 内容 |
|---|---|---|
| PD3Orate | 0 | 0 以外にすると PD3O アルゴリズムでの探索を併用する。SB の 1 ステップごとに PD3Orate × steps 回、変数を更新する |
| phi | 0 | PD3O の挙動（0〜1）。0 に近いと SB に近い挙動になり、1 に近いと探索範囲を絞る |
| detail_level | 0 | 1 にすると、実行可能解がないとき（400 "no result"）に詳細を JSON で返す |
| detail_log | 0 | 1 にすると、実行可能解がないときに制約ごとの違反率をログに出力する |

**サンプラーモード**（ボルツマン分布に従うサンプリング）: `HMCweight=1`、`HMCsteps`（10〜100）と、C・dt・steps を固定して使う。

### 4.6 レスポンス（JSON）

| フィールド | 内容 |
|---|---|
| id | リクエスト ID |
| time | 計算時間（秒） |
| wait | 待ち時間（秒） |
| message | 終了理由: `finished` / `timeout` / `reached` / `max results` / `saturated` |
| runs | 探索した解の総数 |
| value | 最良解の目的値（**定数項は含まない**） |
| result | 最良解の変数配列（例 `[0,1,1,0]`） |
| count | 最良解が得られた回数 |
| param | 最良解を得たときのパラメータ（algo, steps, dt, C） |
| others | 次点以降の解（最大 maxout − 1 個） |

**主なエラー**

- 400 `no result`: 実行可能解が見つからなかった。timeout が短すぎるか、制約が厳しすぎる可能性がある。
  - `detail_level=1` を付けると、次の情報が返る。
    - `main_info.message`
    - `additional.runs`
    - `additional.additional_info`（最新 10 件の `value` / `result` / `param` / `violated_condition`）
    - `additional.violation_rate`（制約ごとの違反率）
- 413: ペイロード過大（既定の上限 2GB）
- 503 `busy` / `engine stopped`
- 504: maxwait 超過

### 4.7 規模の上限（qplib）

| 項目 | 上限 |
|---|---|
| 変数数 | 10,000,000 |
| 制約数 | 1,000,000 |
| 非ゼロ数（qplib テキスト） | 100,000,000 |
| 非ゼロ数（HDF5、Q が疎） | 500,000,000 |
| 非ゼロ数（HDF5、Q が dense） | 800,000,000 |
| 非ゼロ数（Docker 環境、全形式） | 100,000,000 |
| qplib テキストの行数 | 110,000,000 |
| HDF5 ファイルサイズ | 2GB 未満 |

※ 上限内でもメモリ不足で解けない場合がある。

### 4.8 制約処理の内部と信頼性

- 線形制約を内部でどう扱っているか（ペナルティ法か、射影か、主双対法か）は**非公開**。
  - PD3O は主双対型の三作用素分割法なので、制約をラグランジュ乗数的に扱っている可能性はあるが、推測にすぎない。
- **マニュアルのナップサック例（重量上限 10）で、返却解が `[1,1,1,1]`（重量 17 で制約違反）になっている**。ドキュメントの誤記か、実際の挙動かは不明。
  → **クライアント側で、返ってきた解の実行可能性を必ず検証する**。修復（repair）処理も用意しておくべき。

---

## 5. 運用・課金

- サーバは複数のリクエストを受け付けるが、**計算は 1 件ずつ逐次処理**する（`max_requests` の既定は 20、`number_of_workers` の既定は 4）。
- timeout を指定しても、大規模問題では応答が最大 1 分ほど遅れることがある。
- **AWS 版の課金**:
  - 計算時間ベース。timeout を指定した場合は、その timeout 値が課金時間になる（v2.0.1 の追加情報）。
  - AWS Marketplace の掲載単価（2026-11 時点、**秒単価として掲載されていた値。要確認**）:

    | インスタンス | 秒単価 |
    |---|---|
    | p3.2xlarge / g6e.4xlarge | $0.50 |
    | g6e.12xlarge | $1.50 |
    | p4d.24xlarge | $10 |
    | p5.48xlarge | $15 |

    別途 EC2 のインフラ費用がかかる。

## 6. その他のソルバー（参考）

- **shift ソルバー**（v2.1 以降）:
  - 入力は JSON で、ndays、njobs、nemps、jobtime、`empcaps[emp][day][job]`（従業員が実行できるジョブ＝スキルに相当）、`jobconn`（前日→当日のジョブ接続）、`emptime`（総労働時間の上下限）、`dayplan`（日×ジョブの必要人数）、`empplan`（従業員×ジョブの回数）、weights を渡す。
  - **すべての制約を重み付きコスト（ソフト制約）として扱う**。
  - 日単位でジョブを割り当てる問題で、時間軸上の先行制約がないため、MSRCMPSP にそのまま使うのは難しい。
- **pubo ソルバー**: 最大 4 次の項まで扱えるが、制約は使えない。変数は 10 万まで。
- **tsp ソルバー**（TSPLIB 形式）、**qap ソルバー**（qplib 形式）。

## 7. パートナー経由のアクセス

- **Fixstars Amplify**（`amplify.ToshibaSQBM2Client`）:
  - `solver` に `Qubo` / `Qplib` / `Pubo` を指定する。
  - Qplib の対応範囲: 目的関数はバイナリ / 実数変数の 2 次まで。等式・不等式制約はバイナリ / 実数変数の 1 次まで。整数変数は非対応。
  - v0 系では、制約があると自動的に qplib が選ばれていた。送信形式は HDF5。
  - パラメータには `PD3Orate`、`phi`、`detail_level`、`HMCsteps` なども含まれる。
- **Strangeworks**: `toshiba.qplib` で、`ToshibaParameterModel`（PD3Orate / phi など）を使う。

## 8. MSRCMPSP 設計への示唆（次のステップ用のメモ）

1. 整数変数が使えないので、開始時刻・人員割当て・モードは**バイナリ（時間インデックス型など）で表現する**。連続変数を補助的に使うこと（例: makespan）は可能。
2. 目的関数は 2 次まで、制約は線形のみ。資源容量（スキル別・時刻別）、先行関係、割当ての一意性は線形制約で書ける。min-max 型の目的は補助変数と線形制約で表す。
3. 規模の上限（変数 1,000 万、制約 100 万、非ゼロ 1 億〜8 億）と、時間軸の離散化幅・計画期間の兼ね合いを見積もる必要がある。大規模な問題では HDF5 を使う。
4. 制約違反解が返る可能性があるので、**解の検証と修復（repair）処理**を設計に含める。
5. AWS 版では timeout の秒数がそのまま課金に効くので、timeout とパラメータ（algo、PD3Orate、phi）の設計・チューニング方針が必要。

---

## 出典

- [SQBM+ On-premises User Manual（Fixstars Amplify 配布）](https://amplify.fixstars.com/ja/docs/amplify/v1/_downloads/7e21cdf718c667d7e3b709b4d6413bbd/User_Manual-SQBM+_for_On-premises.pdf)
- [SQBM+ for AWS V2 User Manual](https://dfk66cqpwr4ko.cloudfront.net/User_Manual-SQBM%2B_for_AWS_V2.pdf)
- [SQBM+ for AWS Release Notes](https://dfk66cqpwr4ko.cloudfront.net/SQBM%2B_for_AWS_Release_Notes.pdf)
- [AWS Marketplace: SQBM+ for AWS](https://aws.amazon.com/marketplace/pp/prodview-ichzuqyx2vy7a)
- [Fixstars Amplify: Toshiba SQBM+ クライアント](https://amplify.fixstars.com/en/docs/amplify/v1/clients/toshiba.html)
- [Fixstars Amplify: ToshibaSQBM2Client リファレンス (v1)](https://amplify.fixstars.com/en/docs/amplify/v1/reference/generated/amplify.ToshibaSQBM2Client.html)
- [Fixstars Amplify: ToshibaSQBM2Client リファレンス (v0)](https://amplify.fixstars.com/en/docs/amplify/v0/reference/generated/amplify.client.ToshibaSQBM2Client.html)
- [Strangeworks: Toshiba provider](https://docs.strangeworks.com/providers/toshiba)
- [QPLIB ドキュメント（ZIB）](https://qplib.zib.de/doc.html)
- [クラウド Watch: SQBM+ Version 2 発表記事（2023-11）](https://cloud.watch.impress.co.jp/docs/news/1550045.html)
- [AFPBB: SQBM+ 10 億変数対応（Version 2.2）プレスリリース](https://www.afpbb.com/articles/-/3641170)
- [日本マイクロソフト: Azure Quantum 上での SQBM+ 提供（2022）](https://news.microsoft.com/ja-jp/2022/06/28/220628-toshiba-launches-new-sqbm-quantum-inspired-optimization-provider-on-azure-quantum/)
- [Kanao & Goto, Simulated bifurcation for higher-order cost functions (arXiv:2211.09296)](https://arxiv.org/abs/2211.09296v1)

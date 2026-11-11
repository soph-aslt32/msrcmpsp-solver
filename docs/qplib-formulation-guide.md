# SQBM+ qplib ソルバー 定式化ガイド

東芝 SQBM+ の **qplib ソルバー** で表現できる定式化の範囲と、その書き方・注意点をまとめた手引き。実際に解きたい問題（MSRCMPSP など）を定式化するときに、この文書を参照する。

- 作成日: 2026-11-11
- 対象: SQBM+ v2.0.x〜v2.1.x（マニュアル v2.0.3 と AWS 版 v2.1 系）、Fixstars Amplify SDK 1.7.3
- 関連ファイル:
  - [`docs/sqbm-plus-research.md`](sqbm-plus-research.md): 製品全体の調査メモ（バージョン、API、課金など）
  - [`docs/reference/toshiba_qplib.py`](reference/toshiba_qplib.py): 本ガイドの規約を実装した参照実装（書き出し、読み込み、目的値の計算、実行可能性の検査）と自己テスト
  - [`docs/reference/fixtures/`](reference/fixtures/): Amplify SDK が実際に生成した qplib ファイル
  - [`docs/reference/make_probes.py`](reference/make_probes.py) と `docs/reference/probes/`: 未確認事項を実機で確かめるためのプローブファイル（12 章）

## 0. 確度ラベル

各記述には、根拠の強さを示すラベルを付けた。**SQBM+ 実機での検証はまだしていない**ので、【A】【推】【未】の項目は 12 章のプローブで確認すること。

| ラベル | 意味 |
|---|---|
| 【M】 | 東芝のユーザマニュアルに明記されている |
| 【A】 | Amplify SDK 1.7.3 が SQBM+ 向けに生成した送信データで確認した。ローカルの模擬サーバで捕捉した。商用連携実装の挙動として信頼度は高い |
| 【R】 | 参照実装と総当たり計算で、数学的な正しさを確認した |
| 【推】 | 資料からの推定 |
| 【未】 | 未確認。実機での確認が必要 |

---

## 1. 結論: 表現できる問題クラス

```
minimize / maximize   ½ Σ_{(i,j,v)∈Q, i≥j} v·x_i·x_j  +  Σ_i B_i·x_i        （定数項はファイルに書けない）
subject to            LHS_m ≤ Σ_j A_mj·x_j ≤ RHS_m      (m = 1..M)
                      x_i ∈ {0,1}            （バイナリ変数）
                      l_i ≤ x_i ≤ u_i, x_i ∈ ℝ （連続変数）
```

- **変数**: バイナリと有界の連続変数を混在できる【M】【A】。**一般整数は使えない**【M】【A】。
- **目的関数**: 2 次まで【M】。凸である必要はない（QUBO と同じく任意の符号でよい）【推】。
- **制約**: **線形のみ**【M】。等式、片側不等式、両側不等式（範囲制約）のいずれも書ける。
  - 二次制約は送れない。Amplify も二次制約は目的関数へのペナルティに変換していた【A】。
- QPLIB の分類で言えば、目的が Q（二次）、変数が B / C / 混合、制約が B（変数の上下限のみ）/ L（線形）の範囲。東芝の型コードでは `QBB` `QBL` `QCB` `QCL` `QGB` `QGL` の 6 種【M】。
- **解法の性質**:
  - ヒューリスティック（SB アルゴリズム）なので、最適性の証明はない。
  - **実行可能性も保証されない**。マニュアル自身のナップサック例で、制約違反解 [1,1,1,1]（重量 17 > 上限 10）が返っている。参照実装の自己テストで確認した。実機での再現確認は 12 章の U3。
  - 初期解（warm start）は指定できない。
  - 双対値や下界は得られない。
  - 複数の解を受け取れる（`maxout`）。

## 2. 表現可否マトリクス

| 要素 | 可否 | 根拠 | 回避策・備考 |
|---|---|---|---|
| バイナリ変数 | ○ | 【M】 | 変数型コード 1 |
| 連続変数（有界） | ○ | 【M】【A】 | 変数型コード 0。上下限を指定する |
| 連続変数（上下限なし） | △ | 【A】【未】 | Amplify は ±inf の上下限のまま送っていた。SQBM+ が受け付けるかは未確認。**有限の上下限を付けることを推奨** |
| 一般整数変数 | × | 【M】【A】 | バイナリに符号化する（6 章）。Amplify も自動で符号化していた |
| スピン変数（±1） | × | 【A】 | s = 2x − 1 で置き換える |
| 半連続変数・SOS | × | 【推】 | バイナリ ＋ 連続 ＋ 線形制約で表す（5 章 P9） |
| 目的の定数項 | × | 【M】【A】 | ファイルに書く欄がない。クライアント側で加算する |
| 目的の 1 次項 | ○ | 【M】 | B ベクトル。バイナリなら Q の対角に置いてもよい（3 章） |
| 目的の 2 次項（bin×bin、bin×連続、連続×連続） | ○ | 【M】【A】 | 対称化しない ½ 規約に注意（3 章） |
| 目的の 2 次項が 0 個 | △ | 【M】【A】 | 「1 以上」が必須。Amplify はダミー `1 1 0` を自動で追加する |
| 目的の 3 次以上の項 | × | 【M】 | 補助変数で 2 次に落とす（5 章 P13）。pubo ソルバー（4 次まで）は制約を扱えない |
| 線形等式制約 | ○ | 【M】 | LHS = RHS |
| 線形不等式制約（片側・両側） | ○ | 【M】 | **スラック変数は不要**（QUBO との大きな違い） |
| 二次制約 | × | 【M】【A】 | 線形化（P5、P9）するか、目的関数へペナルティとして入れる（P10） |
| 論理制約（AND / OR / 含意） | ○ | 【R】 | 線形化（5 章 P4、P5） |
| indicator 制約・選言 | ○ | 【推】 | big-M で表す（P9）。数値面には注意 |
| min-max（makespan など） | ○ | 【R】 | 連続の補助変数＋線形制約（P8）、またはダミー終端ジョブ |
| 目的の向き | ○ | 【M】 | `minimize` または `maximize`。maximize 時の `value` の符号は【未】 |
| 変数の固定 | ○ | 【推】 | 変数を消して係数をまとめるのが確実。連続型で lb = ub とする方法もある |
| 規模 | — | 【M】 | 変数 1,000 万、制約 100 万、Q の非ゼロ 1 億（テキスト形式）。詳細は 8 章 |
| 初期解・ヒント | × | 【M】 | 指定する手段がない |

---

## 3. 係数規約（最重要）

### 3.1 qplib ソルバーの規約【M】【A】【R】

ファイル（または HDF5）の二次項の各エントリ `(i, j, v)`（i ≥ j）は、目的関数に **v/2 · x_i · x_j** として寄与する。**対角と非対角の両方に 1/2 が掛かる。** 下三角の 1 エントリは対称な 2 要素の代表ではない。

| 書きたい項（自然な係数） | qplib に書く値 |
|---|---|
| c · x_i · x_j（i ≠ j） | `max(i,j) min(i,j) 2c`（二次項。行 ≥ 列） |
| c · x_i²（連続変数） | `i i 2c` |
| c · x_i（バイナリ） | `i c`（一次項 B）または `i i 2c`（対角。x² = x を使う） |
| c · x_i（連続変数） | `i c`（一次項 B）。対角に置くと x² になるので不可 |
| 定数 c | 書けない。クライアントで加算する |

**根拠**

- Amplify の出力例: 目的 `2·b0·r + 0.5·r² − 3r + …` に対して `3 1 4` と `3 3 1` を出力していた（[fixture](reference/fixtures/amplify_mixed.qplib)）。
- HDF5 でも同じで、`3·q0·q1 + 5·q0` は Q(1,0) = 6、Q(0,0) = 10 になっていた。
- マニュアルのナップサック例: 対角に −22 などを置き、全 1 の解の値が −60（= ½·(−120)）になっている。
- マニュアルの pubo 例: 2 次項の値を 2 倍して書くよう指示している。
- 参照実装の自己テストで、これらすべての整合を確認した。

### 3.2 ソルバー間の規約の違い（混同注意）

| ソルバー | 目的関数 | 同じ `3·q0·q1 + 5·q0` を送ったときの Amplify の出力 |
|---|---|---|
| qubo | E = Σ_{i≥j} Q_ij x_i x_j（**1/2 なし**）【M】 | Q(0,0) = 5、Q(1,0) = 3【A】 |
| qplib | ½ Σ_{i≥j} Q_ij x_i x_j + Σ B_i x_i【M】 | Q(0,0) = 10、Q(1,0) = 6【A】 |
| pubo | Σ_d (1/d!) Σ T·x…x + Σ B_i x_i（**d 次の項は d! 倍して書く**）【M】 | `2 1 6`、B は `1 5`【A】 |

→ **qubo 用に作った行列を qplib にそのまま流すと、二次項（と対角に置いた一次項）の寄与が半分になる。** B ベクトルの項やペナルティと混ぜると相対的な重みが崩れ、別の問題を解くことになる。

### 3.3 標準 QPLIB（ZIB）との違い【M】【A】

東芝の「qplib 形式」は、標準 QPLIB（Furini et al. 2019, 付録 B）を参考にした**別物の方言**である。

| 項目 | 標準 QPLIB | 東芝方言 |
|---|---|---|
| 非対角エントリ v の意味 | 対称ヘッセ行列の下三角 → v·x_i·x_j | **v/2·x_i·x_j** |
| 変数型コード | 0 = 連続、**1 = 整数、2 = バイナリ** | 0 = 連続、**1 = バイナリ**（整数はない） |
| セクションの並び | n, m, Q0, b0, q0, Qi, bi, ∞, cl, cu, l, u, 型, 初期点, 名前 | n, m, LHS 既定, RHS 既定, B 既定, 型既定, ub 既定, lb 既定, Q, (pubo), B, A, LHS, RHS, ub, lb, 型（4 章） |
| `# タグ名` のコメント | 任意（無視される） | 必ず付ける。並びが標準と違うので、タグ名で項目を識別していると推定【推】。綴りは完全一致させる（4.2 節） |
| 目的の定数 q0 | あり | **なし** |
| 無限大の値 c∞ | ファイル内で宣言する | 宣言しない。`1.797693134862316e+308` を書く |
| 二次制約、初期点、名前 | あり | なし |
| 問題タイプ | 3 文字（O/V/C の組み合わせ） | `QBB` `QBL` `QCB` `QCL` `QGB` `QGL` のみ。G は「バイナリ＋連続」の意味 |

→ ZIB の配布インスタンスをそのまま投入することはできない。変換が必要（参照実装の `Model` を経由して書き直せばよい）。

### 3.4 返却される `value` の意味

- 返ってくる `value` は 3.1 節の規約で計算した目的値で、**定数項を含まない**【M】【推】。
- クライアント側で自前の評価関数で再計算し、`value` と突き合わせることを推奨する。
  - 規約の解釈がずれていれば、ここで検出できる。
  - 参照実装の `Model.objective(x, with_const=False)` が `value` と一致するはず。

---

## 4. 入力ファイル仕様（実用版）

### 4.1 テンプレート（`QGL` の場合。Amplify と同じ並び）【M】【A】

```
QPLIB_<name>                       ← 1行目: "QPLIB_" で始まる名前（Amplify は "QPLIB_" だけ）
QGL                                ← 2行目: 問題タイプ
minimize                           ← 3行目: minimize / maximize
<n> # number of variables
<m> # number of constraints                                   ← 制約タイプ L のみ
<v> # default left-hand-side value                            ← L のみ（Amplify は -inf）
<v> # default right-hand-side value                           ← L のみ（Amplify は +inf）
<v> # default value for linear coefficients in objective
<0|1> # default variable type                                 ← 変数タイプ G のみ
<v> # default variable upper bound value                      ← 変数タイプ C/G のみ
<v> # default variable lower bound value                      ← 変数タイプ C/G のみ
<k> # number of quadratic terms in objective                  ← k ≥ 1 必須
i j v                                                         ← i ≥ j、1始まり、k 行
<k> # number of non-default linear coefficients in objective  ← 0 件なら省略
i v
<k> # number of linear terms in all constraints               ← L のみ
r j v                                                         ← 制約番号 変数番号 係数
<k> # number of non-default left-hand-sides
r v
<k> # number of non-default right-hand-sides
r v
<k> # number of non-default variable upper bounds             ← C/G のみ
i v
<k> # number of non-default variable lower bounds             ← C/G のみ
i v
<k> # number of non-default variable types                    ← G のみ
i t
```

### 4.2 書式規則

1. インデックスは**変数・制約とも 1 始まり**【M】。
2. 二次項は**行 ≥ 列**（下三角）で書く【M】【A】。
3. 制約係数の行は「制約番号 変数番号 係数」の順【A】。
   - マニュアルの説明文は「variable index」と書いているが、例と Amplify の出力ではこの順になっている。
   - 行の並び順は任意。Amplify の出力も整列していなかった【A】。
4. LHS / RHS の上書き行は「制約番号 値」の順【A】。
5. 無限大は `1.797693134862316e+308`（負なら先頭に `-`）と書く【A】。
   - マニュアルの表記は `1.79769313486232e+308`【M】。
   - どちらも倍精度の最大値を超えるので、strtod などで読めば ±inf になる。
   - `inf` という文字列は使わない（受け付けられるか【未】）。
6. タグは `値 # タグ名` の形。**タグ名の綴りはマニュアル・Amplify と完全一致させ、並び順も 4.1 節に従う**。
   - 順序を入れ替えた場合やコメントがない場合の挙動は【未】。
7. 0 件のセクション（non-default 系）は省略する【M の例】。
   - `0 # …` と書いて通るかは【未】。
8. 同じ (i, j) の重複エントリは避け、事前に合算する。
   - qubo ソルバーでは重複時の動作は未定義とされている【M】。qplib も同様と推定【推】。
9. 二次項が 0 件の場合は、ダミーの `1 1 0` を 1 行置く【A】。
10. 係数の絶対値は 1e+20 以下【M】。制約を含む行が大きすぎる場合は、行ごとにスケーリングする【M】。

### 4.3 問題タイプ別に書く / 書かないタグ【M】【A】

| タグ | 変数 B | 変数 C | 変数 G | 制約 B | 制約 L |
|---|---|---|---|---|---|
| number of constraints / default LHS / default RHS / A / non-default LHS・RHS | — | — | — | 書かない | 書く |
| default variable type / non-default variable types | 書かない | 書かない | 書く | — | — |
| default upper/lower bound / non-default bounds | 書かない | 書く | 書く | — | — |

- 変数タイプ G のとき、Amplify はバイナリ変数にも上下限 (0, 1) を明示していた【A】。参照実装は「最頻値を既定値にする」方式で書く。意味は同じ。

### 4.4 HDF5 形式を使う場合

- `/qubo`（CSR または dense の下三角）、`/linear`、`/constraints/{coeff, lower, upper}` の構成【M】。
- HDF5 には**変数型・上下限を表す欄がない** → **バイナリのみの問題に限られる**【M】【推】。
  - Amplify も、バイナリのみなら HDF5、連続変数を含むならテキストと使い分けていた【A】。
- 値は float32。有効桁は約 7 桁なので、係数レンジに注意。
- 無限大は float32 の `inf` をそのまま入れてよい（Amplify がそうしていた）【A】。マニュアルの表記は 3.40283e+38【M】。
- 制約 0 本でも、空の `/constraints` を付けて送れる【A】。
- バイナリの一次項は `/linear` を 0 にして、Q の対角に 2c として置いてもよい（Amplify の方式）【A】。
- テキスト形式より大きな非ゼロ数を扱える（疎 5 億、dense 8 億）【M】。ファイルは 2GB 未満。

### 4.5 リクエスト

- `POST /solver/qplib?timeout=2&PD3Orate=3&phi=0.5&detail_level=1` のように、クエリ文字列でパラメータを渡す【M】【A】。
- `Content-Type: application/octet-stream`【M】。

---

## 5. 定式化パターン集

（x, y, z はバイナリ、s, w は連続。Σ は線形結合。「行」は qplib の線形制約 1 本を指す）

### P1 割当て・一意選択（one-hot）

`Σ_k x_k = 1` → 等式の行 1 本（LHS = RHS = 1）。

- QUBO ではペナルティ (Σx − 1)² が必要で、重みの調整が課題になる。qplib では**ハード制約として直接書ける**。

### P2 容量・資源制約

`Σ_j a_j x_j ≤ C` → 行 1 本（RHS = C）。

- **スラック変数も二次展開も不要**。両側制約 `L ≤ Σ ≤ U` も 1 本で書ける。

### P3 個数制約（カーディナリティ）

- 高々 k 個: `Σ x ≤ k`
- 少なくとも k 個: `Σ x ≥ k`
- ちょうど k 個: `Σ x = k`

### P4 論理関係（そのまま線形で書ける）

| 関係 | 制約 |
|---|---|
| 含意 x ⇒ y | x − y ≤ 0 |
| 排他（同時に選べない） | x + y ≤ 1 |
| どちらか一方以上（OR） | x + y ≥ 1 |
| ちょうど一方（XOR） | x + y = 1 |
| 同値 | x − y = 0 |

### P5 積の線形化（制約内の積や 3 次以上の項を避ける）【R】

| 関係 | 制約 |
|---|---|
| z = x ∧ y | z ≤ x, z ≤ y, z ≥ x + y − 1 |
| z = x ∨ y | z ≥ x, z ≥ y, z ≤ x + y |
| w = x · s（s ∈ [0, U]） | w ≤ U·x, w ≤ s, w ≥ s − U(1 − x), w ≥ 0 |

- 目的関数の中なら x·y は 2 次項として直接書ける。**制約の中に積が出たときに**この線形化を使う。

### P6 整数量の表現 → 6 章

### P7 連続変数の利用

- **有界にする**。2 次の項は連続×連続、連続×バイナリのどちらも可【A】。
- 主な用途: makespan などの集約値（P8）、違反量（P10）、量の決定。
- SB が連続変数をどう扱うか（PD3O との関係を含む）は非公開【推】。多用する前に小規模で挙動を確かめる。

### P8 min-max（makespan、最大負荷）【R】

- 補助変数 C を置き、`min C` と各 k について `C − f_k ≥ 0`。
  - C が連続なら行 k 本で済む。
  - 目的が線形だけになるので、ダミーの二次項が必要（4.2 節の 9）。
- **代替（バイナリだけで書く）**: 時間インデックス型なら、ダミーの終端ジョブ（全ジョブの後続）を置き、その開始時刻 Σ t·x_end,t を最小化する。

### P9 big-M・indicator・選言

- 「y = 1 なら a·x ≤ b」は `a·x ≤ b + M(1 − y)` と書く。
- M は**必要最小限**にする。大きな M は係数レンジを広げ、float32 や SB のスケーリングで不利になる【推】。
- 構造上可能なら big-M を避ける。例: `Σ a_j z_j ≥ b·y`（z、a ≥ 0 で、上限が自明な場合）。
- 時間インデックス型は big-M を使わずに済むのが利点。

### P10 ソフト制約（違反を許してコスト化）

**(a) 二次ペナルティ（QUBO 流）**: λ(Σ a_i x_i − b)² を展開して目的に加える。

- バイナリの場合、ファイルに書く値は次のとおり。
  - 二次項（i ≠ j）: `4λ a_i a_j`（自然係数 2λa_i a_j の 2 倍）
  - 一次項: `λ(a_i² − 2b a_i)`
  - 定数: λb²（クライアントで加算）

**(b) 弾性制約（qplib ならでは）**: 連続変数 s ≥ 0 を置き、`Σ a x − s ≤ b` として目的に `+λ s` を加える。

- 違反量を線形で正確に測れる。
- ハード制約として通らない（`no result` になる）ときの段階的緩和にも使える。

### P11 二次の目的（相互作用）

- 割当て間のコスト（QAP 型）、同時刻・隣接時刻の組み合わせ、平準化の二乗和 Σ_t (Σ_j r_j x_jt)² など。
- 平準化項のような二乗和は非ゼロ数が急増するので、8 章で数を見積もる。

### P12 時間インデックス型スケジューリングの基本形【R】

変数 x_{j,t} = 1 はジョブ j が時刻 t に開始することを表す（t ∈ [ES_j, LS_j]）。p_j は処理時間。

| 制約 | 式 | 行数 | 非ゼロ数の目安 |
|---|---|---|---|
| 開始は 1 回 | Σ_t x_{j,t} = 1 | J | J·T |
| 先行（集約形） | Σ_t t·x_{j,t} − Σ_t t·x_{i,t} ≥ p_i | \|E\| | 2T·\|E\|（係数は最大 T） |
| 先行（非集約形） | Σ_{τ≤t} x_{j,τ} ≤ Σ_{τ≤t−p_i} x_{i,τ}（各 t） | T·\|E\| | 約 T²·\|E\|（係数はすべて ±1） |
| 資源容量 | Σ_j Σ_{τ=t−p_j+1}^{t} r_jk·x_{j,τ} ≤ R_k（各 t, k） | T·K | Σ_j p_j·T·(使う資源の数) |
| makespan | C − Σ_t (t + p_j)·x_{j,t} ≥ 0 | J | J·T |

- 参照実装の `build_tiny_schedule()` が実例（3 ジョブ、地平 6、容量 1、先行 1 本）。
  - 変数 17、制約 13、非ゼロ 69 になる。
  - 総当たりで実行可能スケジュールが 12 通り、最適 Cmax = 5 であることを確認した【R】。
- 集約形と非集約形の選び方:
  - LP 緩和の強さは SB には関係しない。
  - 集約形は係数レンジが大きく（最大 T）、非集約形は行数・非ゼロ数が多い。
  - どちらが SB に向くかは【未】。両方を試せるように実装しておくのがよい。
- **ES/LS（最早・最遅開始時刻）で x_{j,t} を枝刈りする**と、変数も非ゼロも大きく減る。

### P13 3 次以上の項

- 補助変数 z = x∧y（P5）を導入し、x·y·w → z·w に下げる。
- Amplify の Substitute 方式は、制約 z = x·y をペナルティ（xy − 2xz − 2yz + 3z）で入れていた【A】。qplib なら P5 の 3 本の線形制約で**ハードに**書ける。

### P14 スピン変数

- s = 2x − 1 を代入して x の式に直す。定数項はクライアントで管理する。

### P15 前処理

- 固定できる変数は消去し、その係数を他の項や右辺に畳み込む。
- 冗長な制約は削る。
- 二次項は重複を合算する（4.2 節の 8）。

### 補足: 資源量が別の決定に依存する場合

- 例: 「どの作業者を割り当てるか」y と「いつ開始するか」x の両方に依存する容量制約は、**x·y の積を含む二次制約**になり、そのままでは書けない。選択肢は次の 3 つ。
  1. 結合変数 z_{j,w,t} を使う（線形だが変数が J·W·T に増える）。
  2. P5 で線形化する（補助変数と行が増える）。
  3. 二段階に分解するか、ペナルティとして目的に入れる。
- どれを選ぶかは、具体的な問題の設計段階で、8 章の規模見積もりと合わせて決める。

---

## 6. 整数量の表現

| 方式 | 範囲幅 W = u − l に対する変数数 | 追加の制約 | 値の一意性 | 特徴 |
|---|---|---|---|---|
| one-hot（値ごとに変数） | W + 1 | Σ = 1（等式 1 本） | 一意 | 値ごとの任意のコストを一次項で書ける。時間インデックス型と同じ発想。qplib ではハード制約にできる |
| 順序付き unary（温度計） | W | x_k ≥ x_{k+1}（W − 1 本） | 一意 | 値 = Σx。しきい値条件（≥ k）が 1 変数で書ける |
| 単純 unary（Amplify の Unary） | W | なし | 冗長（同じ値に複数の表現） | 書きやすいが縮退する |
| 2 進（2^k） | ⌈log₂(W+1)⌉ | 必要なら Σ 2^k x ≤ W | 一意 | 変数は最少だが係数レンジが大きい（SB では不利の可能性【推】） |
| Amplify の Default | Linear（係数 1, 2, …, k ＋ 余り）と Binary（1, 2, 4, … ＋ 余り）のうち変数が少ない方 | なし | 冗長になりうる | [0,10] は 1,2,3,4 の 4 変数（Linear）、[0,5] は 1,2,2 の 3 変数（Binary）になっていた【A】 |
| 連続変数で代用 | 1 | — | — | 整数性は失われる。解の丸めと修復が必要 |

- Amplify に整数変数を渡すと、上の Default 方式でバイナリに自動符号化して qplib に送る【A】。
- **方針**: 時刻や選択肢のように「値ごとに意味が違う」量は one-hot にする。数量・個数のように「値の大小だけが効く」量は、順序付き unary か 2 進にする。

## 7. 数値とスケーリング

- 係数は 1e+20 以下【M】。HDF5 は float32 なので、実用上は係数レンジを 1e6 程度以内に収めたい【推】。
- 等式制約の係数と右辺は、**整数にしておくのが安全**。SQBM+ が実行可能性をどの許容誤差で判定しているかは【未】。
- 目的関数のスケールは、algo 154 / 204 などのオートスケール機能がある【M】。それでも目的と制約の係数の桁は揃えておくのが無難【推】。
- big-M は最小限にする（P9）。

## 8. 規模の見積もり

| 上限【M】 | テキスト | HDF5（バイナリのみ） |
|---|---|---|
| 変数 | 10,000,000 | 10,000,000 |
| 制約 | 1,000,000 | 1,000,000 |
| Q の非ゼロ | 100,000,000 | 疎 5 億 / dense 8 億（Docker 環境は 1 億） |
| その他 | 1.1 億行以下 | 2GB 未満 |

- 上限表の「非ゼロ」は、マニュアルでは "the matrix" とだけ書かれていて、Q のみを指すのか A も含むのかは曖昧【M】。
  - 安全側に、Q と A の非ゼロの合計を 1 億以内（テキスト形式）に収める。
  - テキスト形式は総行数 1.1 億以下という制限もある【M】。
- 上限内でもメモリ不足になることがある。GPU メモリは 16GB 以上、大規模なら 32GB 以上が推奨【M】。

**時間インデックス型の目安**（J ジョブ、地平 T、資源 K、平均処理時間 p̄）:

- 変数 ≈ J·T（ES/LS の枝刈りで減る）
- 容量制約の非ゼロ ≈ J·p̄·T·(1 ジョブが使う資源の数)
- 例: J = 100、T = 500、p̄ = 10、K = 5 なら、変数は約 5 万、容量の非ゼロは約 50 万〜100 万で、余裕がある。
- 作業者の割当てまで含む結合変数 z_{j,w,t} では J·W·T（W = 50 なら 250 万）。変数の上限内ではあるが、解の質は要検証。

## 9. SB の特性を踏まえた設計指針【推】

1. **構造的な制約（one-hot、先行、容量）は qplib の制約として書く。** ペナルティ重みの調整という QUBO 最大の難所がなくなる。
2. ただし実行可能性は保証されない。`detail_level=1` の `violation_rate` で、通りにくい制約を診断する。
3. 通りにくい制約は、弾性制約（P10b）や二次ペナルティで段階的に緩和する。
4. 係数は小さく整数にし、レンジを狭くする。big-M は避ける。
5. 変数を減らす（ES/LS の枝刈り、時間刻みを粗くする、対称性を除く）。
6. 連続変数は必要な箇所に限る。挙動を小規模で確かめてから拡大する。
7. パラメータは `algo` の候補と、qplib 専用の `PD3Orate` / `phi` を振って比較する。
   - **AWS 版は `timeout` の秒数がそのまま課金になる**ので、短時間の多数回試行と長時間の 1 回試行を比べて決める。
8. `maxout` で複数解を受け取り、クライアント側で「実行可能かつ最良」の解を選ぶ。

## 10. 解の検証と後処理（必須）

1. 返ってきた `result` を自前のモデルで評価する（参照実装の `Model.violations()`、`Model.objective()`）。
   - Amplify も返却解の実行可能性をクライアント側で検査し、不可解を除外している（実行可能な解がなければ "result has no feasible solution" エラー）【A】。
2. `value` と自前の再計算値を照合する（3.4 節）。ずれていれば規約の解釈を疑う。
3. 不可解は修復する。スケジューリングなら、開始時刻の列から先行・資源を満たすようにシリアルスケジュール生成法でデコードするなど。
4. 400 `no result` は、実行可能解がまったく得られなかったことを示す。`detail_level=1` で次の情報が得られる【M】。
   - 直近 10 解の `violated_condition`
   - 制約ごとの `violation_rate`

## 11. 定式化チェックリスト（問題を持ち込んだときの手順）

1. 決定を列挙し、変数型（バイナリ / 有界連続）に落とす。整数量は 6 章の方式を選ぶ。
2. 目的を 2 次以下で書く。3 次以上なら P13。定数項はメモしておく。
3. 制約を線形で書く。積が出たら P5 / P9。ソフトにする制約は P10 を選ぶ。
4. 変数・行・非ゼロ数を見積もり、8 章の上限と照合する。
5. 係数レンジを確認する（7 章）。
6. 参照実装の `Model` で組み立て、`to_text()` で書き出す。小規模なら総当たりや既存ソルバー（MIP）で答え合わせをする。
7. 実機ではまず 12 章のプローブを流して未確認事項を潰し、その後に本番の問題へ進む。
8. 返却解の検証と修復の処理を用意する（10 章）。

---

## 12. 未確認事項と実機プローブ

SQBM+ にアクセスできるようになったら、まず以下を流す。期待値は参照実装で計算済み。

- プローブファイルは `python3 docs/reference/make_probes.py` で `docs/reference/probes/U*.qplib` に生成済み。
- 送信例: `curl -H "Content-Type: application/octet-stream" -X POST "http://<server>:8000/solver/qplib?timeout=1&detail_level=1" --data-binary @docs/reference/probes/U1_offdiag.qplib`
- 期待値の補足:
  - U3 の真の最適は [1,1,1,0]（value −41）。
  - U6 の最適は (0.8, 0.2)（value 0.36）。
  - U7（maximize）の最大は [1,0] または [0,1] で 0.6。

| # | 確認したいこと | 送るもの | 判定 |
|---|---|---|---|
| U1 | 非対角の規約（v/2 か v か） | 下記 `probe_offdiag` | `[0,0]`（value 0）なら v/2。`[1,1]`（value −0.8）なら標準 QPLIB と同じ v |
| U2 | 上下限なしの連続変数 | `QCL`、既定の上下限 ±inf、min x1² − 2x1、制約 x1 + x2 = 3 | `[1, 2]`（value −1）が返れば対応。エラーなら有界化が必須 |
| U3 | 実行可能性の扱い | マニュアルのナップサック例を timeout=1 で | `[1,1,1,1]`（重量 17 > 10）が再現するか。`detail_level=1` も付ける |
| U4 | タグの厳密さ | U1 のタグ順を入れ替えたもの / `#` コメントを消したもの | エラーか、同じ結果か |
| U5 | 0 件セクション | `0 # number of non-default linear coefficients in objective` を含める | 受理されるか |
| U6 | 等式制約の許容誤差 | 連続変数の等式 x1 + x2 = 1 | 返却値の残差 |
| U7 | maximize 時の value | U1 を maximize にしたもの | value の符号 |
| U8 | 重複エントリ | 同じ (i, j) を 2 行 | 合算されるか、エラーになるか |
| U9 | 無限大の表記 | `inf` / `1e+20` / `1.797693134862316e+308` | どれが受理され、無限大として扱われるか |
| U10 | 連続変数の解の質 | P8 の makespan（連続 C 版とダミー終端版） | 解の質と実行可能率の比較 |

**probe_offdiag**（U1）:

```
QPLIB_probe_offdiag
QBB
minimize
2 # number of variables
0 # default value for linear coefficients in objective
1 # number of quadratic terms in objective
2 1 -2
2 # number of non-default linear coefficients in objective
1 0.6
2 0.6
```

- 規約が v/2 なら、目的は −x1x2 + 0.6x1 + 0.6x2 で、最適は [0,0]（value 0）。
- 規約が v なら、目的は −2x1x2 + 0.6x1 + 0.6x2 で、最適は [1,1]（value −0.8）。

## 13. 参照実装の使い方

```python
import sys; sys.path.insert(0, "docs/reference")
from toshiba_qplib import Model, parse_text

m = Model(name="QPLIB_example")
x = [m.add_binary() for _ in range(3)]
s = m.add_continuous(0, 10)
m.add_quadratic(x[0], x[1], 1.5)        # 1.5·x0·x1 → ファイル値 3
m.add_linear(s, 1.0)
m.add_constraint({x[0]: 1, x[1]: 1, x[2]: 1}, lhs=1, rhs=1)   # one-hot
m.add_constraint({x[0]: 4, x[2]: 2, s: -1}, rhs=0)            # s ≥ 4x0 + 2x2
text = m.to_text()                      # 東芝方言の qplib テキスト
sol = [1, 0, 0, 4.0]
m.violations(sol), m.objective(sol)     # → ([], 4.0)
```

- `python3 docs/reference/toshiba_qplib.py` で自己テストを実行できる（外部依存なし）。テスト内容は次の 4 つ。
  1. マニュアル例の値（−60）の再現と、その解が制約違反であることの確認
  2. Amplify の出力との内容一致
  3. 二次項 0 件時のダミー項
  4. 時間インデックス型の小例の総当たり検証
- Amplify の出力の捕捉は、`ToshibaSQBM2Client.url` をローカルの模擬サーバに向けて `solve()` を呼ぶ方法で行った。
  - Amplify はサーバのバージョンを問い合わせてからリクエストを組み立てるので、模擬サーバは `/version` にも応答する必要がある。

## 14. 出典

- [SQBM+ On-premises User Manual（v2.0.3、Fixstars Amplify 配布）](https://amplify.fixstars.com/ja/docs/amplify/v1/_downloads/7e21cdf718c667d7e3b709b4d6413bbd/User_Manual-SQBM+_for_On-premises.pdf)
- [SQBM+ for AWS V2 User Manual（v2.1 系）](https://dfk66cqpwr4ko.cloudfront.net/User_Manual-SQBM%2B_for_AWS_V2.pdf) / [Release Notes](https://dfk66cqpwr4ko.cloudfront.net/SQBM%2B_for_AWS_Release_Notes.pdf)
- [Furini et al., QPLIB: A Library of Quadratic Programming Instances（付録 B: ファイル形式）](https://optimization-online.org/wp-content/uploads/2017/02/5846.pdf)
- [QPLIB ドキュメント（ZIB）](https://qplib.zib.de/doc.html)
- [Fixstars Amplify: Toshiba SQBM+ クライアント](https://amplify.fixstars.com/en/docs/amplify/v1/clients/toshiba.html)
- [Fixstars Amplify: 変数変換と次数下げ](https://amplify.fixstars.com/en/docs/amplify/v1/intermediate.html) / [制約とペナルティ関数](https://amplify.fixstars.com/en/docs/amplify/v1/penalty.html) / [ファイル入出力](https://amplify.fixstars.com/en/docs/amplify/v1/file_io.html)
- [Strangeworks: Toshiba provider](https://docs.strangeworks.com/providers/toshiba)
- [Ichikawa et al., Constrained Optimization of Higher-Order Cluster-Expansion Hamiltonians for Alloys Using Simulated Bifurcation（arXiv:2609.10310）](https://arxiv.org/abs/2609.10310): SQBM+ v2.0.3 の pubo ソルバーで、制約をペナルティとして扱った実例
- [Kanao & Goto, Simulated bifurcation for higher-order cost functions（arXiv:2211.09296）](https://arxiv.org/abs/2211.09296v1)

# バグレビュー — wayhint(f35d540 時点)

対象はリポジトリ全体(`src/wayhint/`、`scripts/`、`tools/`)。セキュリティ脆弱性とスタイルは対象外。
レビューは 2026-10-16。モジュール群ごとに読み取り専用のレビュー担当 5 本(daemon/IPC/CLI、
YAML/設定/選択、context/UI、UI と Wayland の追い読み、scripts/tools)で読み、主要な指摘は本文の
`path:line` を開いて照合した。🔴 の 4 件と 🟡 の主要なものは、コードを読み直すか小さな再現スクリプト
(`.venv/bin/python`、GUI なし)で裏を取ってある。GUI(`./scripts/check-gui`)での再現はしていない。

## 対応状況(2026-10-16)

🔴・🟡・🟢 の 36 件は作業ツリーで修正済み(未コミット)。それぞれに、そのバグで落ちるテストを足した。
例外は 🟢-11 の一部で、自動生成する `.desktop` 用の `rewrite_exec` は手を入れていない。
❓ の 11 件は手を付けていない(再現か仕様の判断が要るため)。仕様の判断は DECISIONS 0050 に記録した。

## 集計

| 重大度 | 件数 |
|---|---|
| 🔴 高 | 4 |
| 🟡 中 | 16 |
| 🟢 低 | 16 |
| ❓ 要確認 | 11 |

## 構造的な問題

同じ形の原因が複数箇所で繰り返されている。個々の項目はこの下の各節にある。

1. **ガードが入口の 1 つにだけある。** 同じ状態を扱う兄弟の入口に同じ確認が無い。
   - `toggle` は編集・検索中を守るが、`show` / `refresh` は守らない(🟡-3)。
   - `validate` は警告を失敗にしないが、CLI の書き込み系は警告でも止まる(🟡-11)。
   - `SheetStore.reload` は読めたときだけ include を解決し直し、ファイルが消えたときはしない(🟡-6)。
2. **「一部」を「全体」として扱っている。**
   - 読めたシートの一覧(`store.sheets`)を、「ディスク上にあるファイル名」の代わりに使っている(🔴-1)。
   - ウィンドウは検索ボックス・`_mode`・メッセージ行を 1 つずつしか持たず、ワークスペースごとの
     view で共有している。そのため再描画の経路が、他の view の状態や一回きりの表示を上書きする
     (🟡-2、🟡-5、🟢-1)。
3. **境界での例外の変換が狭い。** 想定外の型が来ると、予定していない経路に入る。
   - `send_command` が生の `OSError` を外へ出す。
   - `on_activate` は `SystemExit` しか捕まえない(🔴-4)。
   - herdr の `UnicodeDecodeError`(🟢-5)、resolver の `applies_to`(🟢-6)。
4. **同じ規則のコピーがずれている。**
   - id の正規表現が `yaml_store` と `config` に 2 つある(🟢-7)。
   - JSON Schema と検証器が食い違う(🟢-8)。
   - include の解析が `config._include_refs` と `yaml_store._include_refs` で別々に実装されている。
5. **全部の確認が済む前に書き込み・削除を始める。**
   - setup-terminals は wrapper を書いた後に launcher の読み込みで落ちる(🟡-13)。
   - demo は前回の録画を消してから事前チェックで拒否する(🟡-15)。
   - gen-protocol は生成物を空にしてから失敗しうる(🟢-10)。

---

## 🔴 高(本番でデータ破損・停止・誤動作につながる)

着手すべき順に並べた。上の 2 件は、ユーザーが手で書いたシートの内容を黙って失う。

### 🔴-1 quick add が、読み込めていない既存のシートファイルを上書きする

- **場所**
  - `src/wayhint/daemon.py:857` `existing_ids=[s.id for s in self.store.sheets],`
  - `src/wayhint/yaml_store.py:1192` `sheet_id = slug(source or "", existing_ids, now)`
  - `src/wayhint/yaml_store.py:1218` `return hints_dir / f"{sheet_id}.yaml", doc`
  - `src/wayhint/yaml_store.py:914` `os.replace(tmp, path)`(`_write_checked`)
- **何が起きるか:** 新しいシートの名前を決めるとき、`store.sheets`(読み込めたシート)だけを
  「使われている id」として渡している。`hints/<lang>/foot.yaml` が次のどちらかだと `store.sheets` に入っていない。
  - daemon の起動時から構文エラーで、最後に読めた内容が無い。
  - id とファイル名が一致せず、読み込みを拒否されている。

  この状態で foot の上で quick add すると、`slug` は `foot` を空いている名前とみなす。`create_sheet` が
  `foot.yaml` を返し、`os.replace` が存在確認なしに置き換えるので、元のヒントがすべて消える。
  `_stale_sheet(None)` はシートの無い context を素通りさせるので、これも止めない。
- **再現条件:** 構文エラーのある `foot.yaml` を置いた状態で wayhintd を起動する。foot の上で編集モードに
  入り、quick add で 1 件保存する。レビュー時に、ストアを使った再現スクリプトで置き換わることを確認した。
- **修正方針:** 新しい名前は、hints ディレクトリにある全ファイルの stem(`store.errors` のパスも含む)と
  重ならないように選ぶ。新規作成の書き込みは排他作成にして、既存ファイルがあれば失敗させる。

### 🔴-2 フォームで保存すると、kind が「持たない」`key` / `command` がファイルから消える

- **場所**
  - `src/wayhint/ui/editmode.py:450-451` `out[name] = draft.value(name).strip() or None if name in wanted else None`
  - `yaml_store.update_hint`(`base.update(fields)`)
  - フォームは該当行を出さない: `src/wayhint/ui/window.py:1070-1073`
- **何が起きるか:** `draft_fields` は、kind に無いフィールドを `None` にして返す。`shortcut` なら `command`、
  `note` なら `key` と `command` が `None` になる。`update_hint` はそれをそのまま上書きする。
  `docs/SHEET-FORMAT.md:134` は、手書きの `shortcut` が `key` と `command` の両方を持つことを認めている。
  フォームにはその行が出ないので、ユーザーは消える値を見ないまま保存することになる。
- **再現条件:** `kind: shortcut`、`key: C-b`、`command: tmux …` と書いたヒントを編集モードで開き、
  タイトルだけ変えて Enter を押す。ファイルから `command` が消える。
- **修正方針:** 既存ヒントの編集(`hint_id` あり)では、kind が持たないフィールドを `fields` に入れず、
  元の値を残す。値を消すのは quick add のときと、ユーザーが kind を変えたときだけにする。

### 🔴-3 ヒントを編集・並べ替え・削除すると、隣のヒントのコメントがずれたり消えたりする

- **場所**
  - `src/wayhint/yaml_store.py:984-999` `_carry_comments`。`update_hint` :1032、`set_favorite` / `toggle_favorite`、
    `normalize_sheet` :1110 から使われる。
  - `src/wayhint/yaml_store.py:1065-1079` `swap_hints`(`hints.ca.items[i]` / `[j]` だけを入れ替える)
  - `src/wayhint/yaml_store.py:1052-1062` `delete_hint`
- **何が起きるか:** ruamel は、2 つのヒントの間にあるコメント行を、前のヒントの最後のキー
  (`ca.items[last_key]`)に付けて保持する。
  - `_carry_comments` は、作り直した 12 キーの map にキーごとにコメントを写す。そのため、もう最後では
    なくなったキーにコメントが残り、ヒントの途中に出力される。
  - `swap_hints` はシーケンス番号の側だけ入れ替えるので、見出しコメントが元の位置に残る。
  - `delete_hint` は、次のヒントの見出しコメントを消し、削除したヒント自身の見出しを残す。

  これは DESIGN §4 の「直前のコメントを付け直す」「直前のブロックコメントも消す」と、D2 の
  「対象ヒントの並び以外は変えない」に反する。
- **再現条件:** `- id: a …` の直後に、空行を挟まず `  # --- second section ---`、続いて `- id: b`、
  `  # --- third ---`、`- id: c` と書いたシートを用意する。
  - `update_hint(d, "a", {"title": "A2"})` で、コメントが a の `key:` と `command:` の間に入る。
  - `swap_hints(d, "a", "b")` で、`third` が a の上に、`second` が c の上に来る。
  - `delete_hint(d, "a")` で、b の見出しが消える。

  3 つともレビュー時に再現した。既存テストは、空行のある配置で中間と末尾の組み合わせしか見ていない。
- **修正方針:** ヒントを作り直す・動かす前に、ヒントの最後の値に付いた後続コメントを外し、新しく最後に
  なったキーへ付け直す。入れ替えと削除では、「ヒント i の上のコメント」を「ヒント i-1 の後続コメント」
  (i=0 ならシーケンスの先頭コメント)として扱う。空行なしの配置と先頭ヒントのテストを足す。

### 🔴-4 2 つ目の wayhintd の起動失敗が、動いている daemon のソケットを消し、終了コード 0 で終わる

- **場所**
  - `src/wayhint/daemon.py:167-174` `stop()` は、自分が bind したかに関係なく `self.socket_file.unlink()` する。
  - `src/wayhint/daemon.py:1149-1158`: `ipc.send_command("ping", …, timeout=0.5)` が `DaemonUnavailable` 以外を
    投げる場合と、`srv.bind(...)`。
  - `src/wayhint/ipc.py:130` `chunk = s.recv(4096)` は try の外にあり、`TimeoutError` や `ConnectionResetError` が
    そのまま出る。
  - `src/wayhint/daemon.py:1230-1240`: `on_activate` は `SystemExit` しか捕まえず、`shutdown` には `daemon.stop()` が
    無条件に接続されている。
- **何が起きるか:** `activate` で `SystemExit` 以外の例外が出ると、PyGObject はそれを表示して戻るだけで、
  `run()` は 0 を返し、`shutdown` も発火する。そのため `stop()` が、先に動いている daemon のソケットを削除する。
  以後、`wayhint toggle` はすべて「wayhintd is not running」になるが、daemon 自体は動き続けている。
- **再現条件:**
  - (a) 1 つ目の daemon が 0.5 秒を超えて応答しないとき(Herdr の問い合わせだけで最大 1.5 秒、
    `context/herdr.py:41`)に 2 つ目を起動する。ping が `TimeoutError` になる。
  - (b) autostart と手動起動が同時に走る。両方ともソケットが無いと判断し、負けた側の `bind` が
    `EADDRINUSE` になる。
- **修正方針:**
  - `stop()` は、自分が bind したとき(`_server` を設定したとき)だけソケットを消す。
  - `send_command` は、送受信中の `OSError` をすべて `DaemonUnavailable` に変換する。
  - 起動に失敗したら、終了コードを非 0 にする。

---

## 🟡 中(特定条件で誤った結果になる、運用で気づきにくい)

### 🟡-1 ワークスペースのキーが最後に届いたイベントで決まり、id が name に負ける

- **場所**
  - `src/wayhint/context/workspace.py:218-219` `handle.dispatcher["id"] = lambda h, value: self._rekey(oid, ws_id=value)` /
    `…["name"] = lambda h, value: self._rekey(oid, name=value)`
  - `src/wayhint/context/workspace.py:225-230` `new = workspace_key(ws_id, name, oid)`。片方の値しか渡されない。
  - `src/wayhint/daemon.py:1121-1122` `for gone in set(self._open) - known: del self._open[gone]`
- **何が起きるか:** `_rekey` には届いたイベントの値しか渡らないので、後から届いた方がキーになる。
  ext-workspace は `id` の後に `name` を送るため、`workspace_key` の docstring が言う「id 優先」が成り立たない。
  - (a) 表示中のワークスペースの名前が変わるとキーが変わる。`_apply_workspace` が「消えたワークスペース」
    として view を捨てるので、編集中の下書きも消え、オーバーレイが閉じる。
  - (b) 出力ごとに別のグループで同じ名前のワークスペース(例えばどちらも「1」)があると、キーが衝突する。
    `_state` を上書きし合い、片方を remove するともう片方の状態も消える。
- **再現条件:**
  - (a) id と name の両方を送るコンポジタで、オーバーレイを開いたワークスペースの名前を変える。
  - (b) 2 つの出力が同じ名前のワークスペースを持つ。labwc 0.20.2 は id を送らないので、(b) だけが起きる。
- **修正方針:** handle ごとに id と name を保持してからキーを計算し、id が届いていれば常にそれを使う。
  名前の変更は、`_open` のキーの付け替えとして扱う。

### 🟡-2 検索のまま隠したワークスペースの入力が、別のワークスペースでの検索に上書きされる

- **場所**
  - `src/wayhint/daemon.py:1124-1134`: `_leave_shown_search()` を呼ぶのは、restore するときか `is_shown()` のときだけ。
  - `src/wayhint/daemon.py:579` `_leave_search` は `self.window.search_text()` を読む。
  - `src/wayhint/ui/window.py:562-565` 検索に入るときに `self._search.set_text(self._query)`。
- **何が起きるか:** ワークスペース A で検索中に `Super+h` で隠すと、A の view は `search` のまま残り、入力中の
  文字はウィンドウ共有の検索ボックスにしか無い。その状態で B に移って検索を始めると、ボックスが B の
  フィルタで上書きされる。A に戻ると restore が B の検索を終え、A を `search` モードのまま、検索前の
  フィルタで出す。A で入力していた文字は失われる。`docs/HOTKEYS.md:32`「Leaving the workspace … ends
  search and saves the filter: returning shows normal mode」と食い違う。
- **再現条件:** A で `Super+Shift+h` を押して文字を入力し、`Super+h` で隠す。B に移って `Super+Shift+h` を押し、
  別の文字を入力する。A に戻る。
- **修正方針:** ワークスペースが変わるたびに、表示中かどうかに関係なく、表示していた view の検索を終えて
  フィルタを保存する。隠した view を戻ったときに自動で再表示するかどうかも、仕様として決めて HOTKEYS に書く。

### 🟡-3 `wayhint show` / `refresh` が、編集モードと下書きを黙って捨てる

- **場所**
  - `src/wayhint/daemon.py:978-982`: `refresh()` は表示中なら `self.show()`。
  - `src/wayhint/daemon.py:292-296`: `show()` は `_open_here(ctx)`。
  - `src/wayhint/daemon.py:371-376`: `previous.mode == "search"` のときだけ扱い、それ以外は
    `WorkspaceView(context=ctx, …)`(normal)で置き換える。
- **何が起きるか:** `toggle` は、編集・検索中の作業を守る分岐を持っている(`daemon.py:337-347`、0014 D4)。
  `show` / `refresh` にはその分岐が無く、`_present` の `close_form()` でフォームの下書きが消え、編集モードも
  抜ける。`refresh` は README:250 で、マウスだけで使う手段として案内されている。
- **再現条件:** `Super+Ctrl+h` を押し、`a` でフォームを開いて入力する。その状態で `wayhint refresh` を実行する。
- **修正方針:** `show` / `refresh` にも `toggle` と同じ編集・検索のガードを入れ、そのまま再表示するか拒否する。
  捨てるのが仕様なら、HOTKEYS と README に書く。

### 🟡-4 検索中にリストへ移ると、Esc が効かない

- **場所**
  - `src/wayhint/ui/editmode.py:206-213`: リスト側の `simple` に `Escape` が無い
    (`"c"`, `"Return"`, `"KP_Enter"`, `"Down"`, `"KP_Down"` だけ)。
  - `src/wayhint/ui/window.py:692`: `if self._mode == "normal" or not self._editable_focused(): return False`。
    このため 696-698 の `Escape` → `end_search()` は、入力欄にフォーカスがあるときしか動かない。
  - `src/wayhint/ui/window.py:624`: Esc は検索ボックスの `stop-search` に任せているが、`_focus_list` で
    ボックスはフォーカスを失っている。
- **何が起きるか:** 検索中に ↓ でリストに移ってから Esc を押しても、検索から抜けず、キーボードも
  EXCLUSIVE で取られたまま残る。HOTKEYS.md:52「`Enter` / `Esc` ends search」と、window.py:591 のヘルプ
  「Enter/Esc leave」に反する。GUI テスト(`tests/test_gui_headless.py:638`)は、ボックスにいるときの Esc しか見ていない。
- **再現条件:** `Super+Shift+h` を押し、`foo` と打ち、↓、Esc の順に押す。
- **修正方針:** `search_action` の、入力欄にフォーカスが無い側で `Escape` を `END_SEARCH` に割り当てる。
  `search_action` のテストと GUI テストに 1 ケースずつ足す。

### 🟡-5 「saved / deleted / restored」のメッセージが、ファイルの再読み込みですぐ消える

- **場所**
  - `src/wayhint/daemon.py:833`(`saved`)、`:878`(`deleted`)、`:891`(`restored`)の `show_message`
  - 書き込み後、ファイル監視が `_debounced_reload` → `_after_reload`(`daemon.py:231-235`)→ `present_context` /
    `show_issues` と進む。
  - `src/wayhint/ui/window.py:877`(`_render_header` → `_show_standing()`)と `:446`(`show_issues` → `_show_standing`)が、
    メッセージ行を上書きする。
- **何が起きるか:** `show_message` の docstring(window.py:469)は「次のモード切り替えまで残る」と言っているが、
  書き込み直後の再読み込みが約 200 ms で消してしまう。`d d` の後の「deleted X」が見えないので、`u` で戻せる
  手がかりも失われる。テストの fake window(`tests/test_daemon_edit.py:43`)は、この挙動を模していない。
- **再現条件:** 編集モードでヒントに `d d` を押す。フォームで保存したときも同じ。
- **修正方針:** 一回きりのメッセージを window 側で保持し、モード切り替え以外の再描画では `_show_standing` が
  消さないようにする。

### 🟡-6 シートファイルを消しても、include で混ぜたヒントが出続ける

- **場所:** `src/wayhint/yaml_store.py:777-780`

  ```python
  if not path.exists():
      self._sheets.pop(path, None)
      self.errors.pop(path, None)
      return True
  ```

  読めたときの分岐(:787)は `self.resolve()` を呼ぶが、この分岐は呼ばない。daemon の `_debounced_reload`
  (`daemon.py:285`)は `store.reload(path)` しか呼ばない。
- **何が起きるか:** `b.yaml` を消しても、`includes_for(a)` は b を返し続ける。消えたファイルを指すヒントが
  表示に残り、「include: no sheet with id 'b'」の警告も出ない。他のシートが読み直されるまでこのまま。
- **再現条件:** `a.yaml` に `include: [b]` と書いた状態で `b.yaml` を削除する。
- **修正方針:** 削除の分岐でも `resolve()` を呼ぶか、`reload` の結果に関係なく最後に 1 回呼ぶ。

### 🟡-7 config.yaml の `include` に無い id は、シートの数だけ、各シートのファイルの警告として出る

- **場所:** `src/wayhint/yaml_store.py:702-706`

  ```python
  issues.append(Issue(sheet.path, 1, f"include: no sheet with id {name!r}", "warning"))
  ```

  自分自身を指す場合(:697)は `own` を見るが、この分岐は見ない。
- **何が起きるか:** config.yaml の既定の `include: [nope]` が、自前の include を持たない N 枚のシートについて、
  `<sheet>.yaml:1` の警告として N 回出る。どのシートのファイルにも `include` は書かれていない。
  `check-sheet`(`sheet_check.py:125-126`)も、これを調べたシートの警告として出す。
- **再現条件:** `resolve_includes([a, c], [IncludeRef("nope")])` を呼ぶ。
  `c.yaml:1: warning: include: no sheet with id 'nope'` が出る。
- **修正方針:** 既定の include に無い id は、config.yaml の問題として 1 回だけ報告する。シートの警告にするのは、
  そのシート自身の `include`(`own`)が無い id を書いたときだけにする。

### 🟡-8 サイズに `.nan` / `.inf` を書くと検証を通り、配置の計算で落ちる

- **場所**
  - `src/wayhint/models.py:51-54`: `if raw < 0: …` / `return cls(float(raw), "px")`(NaN は `< 0` が偽になる)
  - `src/wayhint/models.py:69` `return round(self.value)`
  - 呼び出し元: `ui/geometry.py:43-44`
- **何が起きるか:** config の `overlay.width: .nan` や、シートの `display.width: .inf` が `Size` として受け入れられる。
  `wayhint validate` も何も言わない。オーバーレイを出すときに `to_px` が `ValueError` / `OverflowError` になり、
  配置の経路で例外が出る。
- **再現条件:** `parse_global_config` に `overlay: {width: .nan}` を渡して `to_px(1000)` を呼ぶ。例外になる。
- **修正方針:** `Size.parse` で `math.isfinite` でない値を拒否する。px に妥当な上限を設けることも検討する。

### 🟡-9 数字だけの `key` / `command` が、書いたとおりに残らない

- **場所:** `src/wayhint/yaml_store.py:386-387`

  ```python
  if isinstance(value, (int, float)) and not isinstance(value, bool):
      return str(value)  # e.g. ``key: 5``
  ```

- **何が起きるか:** SHEET-FORMAT は「`key: 5` のように数字だけ書いても文字列として扱う」と書いている。
  実際には、YAML が数値として読んだ値を印字し直すので、書いた文字と変わる。
  - `1.10` は `1.1` になる。
  - `010` は `10`、`0x1F` は `31`、`0o17` は `15` になる。
  - `1e3` は `1000.0`、`1_000` は `1000`、`.inf` は `inf` になる。

  この値が、表示・検索・コピーにそのまま使われる。
- **再現条件:** `key: 010` や `command: 1.10` と書いたヒントを表示する。
- **修正方針:** スカラーの元の文字列を使う(ノードから取る)。または、素の十進整数以外の数値は
  「引用符で囲む」エラーにする。どちらにしても文書をそれに合わせる。

### 🟡-10 config.yaml の `logging.level` が daemon 自身のロガーに効かず、既定値が `-v` を打ち消す

- **場所**
  - `src/wayhint/daemon.py:69` `log = logging.getLogger("wayhintd")`(`wayhint` の子ではない)
  - `src/wayhint/daemon.py:197` `logging.getLogger("wayhint").setLevel(self.config.log_level.upper())`
  - `src/wayhint/daemon.py:1213-1216` `basicConfig(level=INFO if args.verbose else WARNING)`
- **何が起きるか:**
  - `logging: {level: info}` にしても `-v` なしなら、daemon.py の「request: toggle」などの info は、root の WARNING で落ちる。
  - `-v` を付けても既定の config なら、`wayhint` が WARNING に設定されるので、`wayhint.context.*` や
    `wayhint.ui.window` の info が落ちる。

  docs/CONFIG.md の logging 節(「daemon のログの詳しさ」「`-v` で info」)と合わない。
- **再現条件:** 上の 2 通り。どちらもレビュー時に再現スクリプトで確認した。
- **修正方針:** daemon のロガーを `wayhint.daemon` にする。`-v` と `logging.level` の優先順位を 1 つに決めて適用する。

### 🟡-11 CLI の編集コマンドが、警告だけでも書き込みを拒否する

- **場所:** `src/wayhint/cli.py:190-196`

  ```python
  result = load_all(root)
  if result.issues:
      …
      raise CommandError("fix the problems above first; nothing was written")
  ```

  `cmd_validate`(`cli.py:66-76`)は `result.errors` で判定し、警告では失敗しない(DECISIONS 0026)。
- **何が起きるか:** 無関係なシートに `include: no sheet with id 'x'` の警告が 1 つあるだけで、`add`・`edit`・
  `remove`・`favorite`・`move`・`format`・`schema --write` がすべて exit 1 になる。オーバーレイの編集モードは
  止まらない。文書にもテストにも、この挙動の記述は無い。
- **再現条件:** 任意のシートに `include: [nope]` と書いて `wayhint add probe --sheet <id> --key x` を実行する。
  `validate` は exit 0 なのに、add は exit 1 になる。
- **修正方針:** `result.errors` で判定し、警告は表示するだけにする。

### 🟡-12 setup-terminals: 1 行に 2 つの端末があると片方しか書き換わらず、その後も直らない

- **場所**
  - `scripts/setup-terminals:560-561` `for path, lines in plan.edits.items(): edits.setdefault(path, {}).update(lines)`
  - `scripts/setup-terminals:358` `if "-wayhint" in line: continue`
- **何が起きるか:** 端末ごとの計画は、それぞれ元の行全体から作った置き換え後の行を持っている。同じ行番号なので、
  後の計画が前の計画を上書きする。適用後の行には `kitty-wayhint` が含まれるため、次の実行からは
  :358 が行ごと飛ばす。残った `foot` の直接起動は直らず、dry run も「完了」と言って exit 0 になる。
- **再現条件:** waybar の 1 行に `"on-click": "foot", "on-click-right": "kitty"` と書いて `--apply foot kitty` を
  実行する。レビュー時に再現した。
- **修正方針:** 1 行に全部の端末の置き換えを順に適用する。「wrapper を指しているか」は、行全体の部分一致では
  なくコマンドごとに判定する。

### 🟡-13 setup-terminals: dry run は通る launcher で、`--apply` が wrapper を書いた後に落ちる

- **場所**
  - `scripts/setup-terminals:354` `lines = path.read_text(errors="replace").splitlines()`
  - `scripts/setup-terminals:377` `original = path.read_text()`(厳密なデコード)
- **何が起きるか:** UTF-8 として不正なバイトを含む launcher を、走査では緩く読んで書き換え対象として報告する。
  `--apply` では `edit_lines` が `UnicodeDecodeError` で traceback を出す。その時点で wrapper と `.desktop` は
  書き込み済み(:556-557)で、辞書で先にあった launcher も編集済みになりうる。バックアップの一覧も出ない。
- **再現条件:** `~/.config/labwc/menu.xml` のコメントに `\xe9` を含めて `--apply foot` を実行する。
  レビュー時に再現した。
- **修正方針:** 両方で同じ読み方をする(または両方でデコードできないファイルを飛ばす)。
  書き込みを始める前に、計画したすべての編集を検証する。

### 🟡-14 demo: HeadlessSession が残した HOME を、DemoSession が消してしまう

- **場所**
  - `tools/demo/session.py:307-311`: `self.session.__exit__(*exc)` の後に、`if home is not None and home.exists(): shutil.rmtree(home, …)`
  - 対応する約束: `tools/headless.py:266-272`(プロセスグループが空になったのを確認できなければ、
    `if left: return  # both directories stay`)
- **何が起きるか:** headless 側は「止まりきらないプロセスがあるので残す」と表示してディレクトリを残す。
  ところが demo 側が、まだ動いているかもしれないプロセスの下でそれを消す。表示された案内は嘘になり、
  原因を調べるためのログも消える。
- **再現条件:** 録画の終了時に、プロセスグループが 5 秒以内に空にならない(例えば止まらない Herdr)。
- **修正方針:** `_tear_down` が、ディレクトリを残したかどうかを返すようにする。demo の後片付けは、
  削除されたときだけ行う。

### 🟡-15 demo: `--record` が、事前チェックで拒否される前に前回の録画を消す

- **場所:** `tools/demo/__main__.py:336-339`: `out = _output_dir(...)`(既存の録画を rmtree)、`out.mkdir(...)`、
  その後に `work = sess.workspace(show.name, language)`。この呼び出しは :340 の `try` の外にある。
- **何が起きるか:** `workspace()` は、前回の録画が異常終了して `/tmp/wayhint-demo/<showcase>-<lang>` が残っていると
  `DemoError` を投げる。そのときにはもう `out/<lang>/<variant>` の採用済みの録画が消え、空のディレクトリが残る。
  :352-355 の「空のディレクトリは無いより悪い」という後片付けも、`try` の外なので走らない。
- **再現条件:** 録画を途中で落として作業ディレクトリを残し、もう一度 `--record` を実行する。
- **修正方針:** 破壊的でないチェック(`workspace`、`prepare_config`)を先に済ませてから出力先を空にする。
  `workspace` の呼び出しも `try` / `finally` の中に入れる。

### 🟡-16 headless: 後片付けで、バスに他と同時に SIGTERM を送っている(コメントの順序と違う)

- **場所:** `tools/headless.py:249-253`: `for proc in reversed(started): … self._signal_group(proc, signal.SIGTERM)` の後で、
  別のループで wait している(:254-260)。:243-246 のコメントは「バスは最後に落とす。動いているコンポジタの
  下から抜くと AT-SPI のクライアントが止まる」と言っている。
- **何が起きるか:** 逆順に送ってはいるが、間で待たないので、dbus-daemon はコンポジタやクライアントがまだ
  終了処理中のうちに終わる。コメントが避けたいと書いている状況そのものが起きる。
- **再現条件:** AT-SPI を使うクライアントがいる GUI テストを、何度も実行する。
- **修正方針:** クライアント・daemon・コンポジタに送って待ってから、バスに送る。

---

## 🟢 低(防御的に直したい、現状は実害なし)

### 🟢-1 `present_context` が、前の view の `_mode` でキーボードモードを決めてから `set_mode` する
- **場所**
  - `src/wayhint/daemon.py:387-391`: `present_context(...)` の後に `set_mode(view.mode, refocus=False)`
  - `src/wayhint/ui/window.py:434-438`: `set_visible(True); self._sync_keyboard_mode()`
- **何が起きるか:** 編集中に Close すると、`close()` は window の `_mode` を戻さない。次に別のウィンドウで
  `Super+h` を押すと、一瞬だけ EXCLUSIVE を要求してから NONE に戻る。最終状態は正しいが、間に commit が
  入るとキーボードが一瞬奪われる。
- **修正方針:** surface を map する前にモードを適用するか、`close()` で window を normal に戻す。

### 🟢-2 キーボードモードの docstring がコードと違う
- **場所**
  - `src/wayhint/ui/window.py:4-6`「search and edit are ON_DEMAND」
  - `src/wayhint/ui/editmode.py:99`「(ON_DEMAND) or not (NONE)」
  - 実装は `window.py:536` `LayerShell.KeyboardMode.EXCLUSIVE if grab else …`(`:527` の docstring は EXCLUSIVE を選んだ理由を書いている)
- **修正方針:** 両方の docstring を EXCLUSIVE に直し、DESIGN の編集モード §1 の記述も確かめる。

### 🟢-3 幅が決まらないとき、前の `set_size_request` が残る
- **場所:** `src/wayhint/ui/window.py:817-819`: `if place.width: self.set_size_request(...)`
- **何が起きるか:** 幅を `%` で書いていて出力が分からないとき(`geometry.py:41-42` が None を返す)、前の
  context の最小サイズが残る。`wayland.py:235` は、複数出力で `output_enter` の無い toplevel や、v4 未満の
  wl_output では出力を返さない。
- **修正方針:** 毎回 `set_size_request` を呼び、分からないときは `-1` を渡す。

### 🟢-4 主の provider の `ContextError` が何であっても、Wayfire への切り替えが恒久化する
- **場所:** `src/wayhint/context/select.py:51-53, 57-66`(`if self._chosen is None: self._chosen = p`)
- **何が起きるか:** module docstring は「プロトコルが無いとき」と言うが、実装では registry の roundtrip 失敗
  (`wayland.py:142-144`)のような一時的な失敗でも、以後ずっと fallback を使う。
- **修正方針:** 「プロトコルが無い」専用の例外のときだけ切り替えて記憶する。それ以外は、その 1 回の失敗として扱う。

### 🟢-5 herdr の出力が UTF-8 でないと、警告ではなく traceback になる
- **場所:** `src/wayhint/context/herdr.py:97-106`(`text=True` で、`except (OSError, subprocess.SubprocessError)` と
  `except json.JSONDecodeError` だけ)
- **何が起きるか:** `UnicodeDecodeError` が `_call` の外へ出て、`resolver.py:60-62` が「adapter bug」として
  traceback 付きで記録する。結果(窓のシートを使う)は同じ。
- **修正方針:** `_call` で `UnicodeDecodeError`(`ValueError`)も捕まえる。

### 🟢-6 `applies_to` が resolver の try の外にある
- **場所:** `src/wayhint/context/resolver.py:53` `if not provider.applies_to(snap.app_id)`(:60 の `except Exception` の範囲外)
- **何が起きるか:** adapter のバグがここで出ると `resolve()` ごと失敗する。コメントの「adapter のバグで
  オーバーレイを落とさない」に反する。
- **修正方針:** `applies_to` も同じ try の中に入れる。

### 🟢-7 id の正規表現の `$` が末尾の改行を許す(コピーが 2 つある)
- **場所**
  - `src/wayhint/yaml_store.py:56` `_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")`
  - `src/wayhint/config.py:101`(同じパターン)
  - `.match` で使う箇所: `yaml_store.py:399,448,460`、`config.py:114,120`
  - `schema.py:43,90,100,106` が同じパターンを書き出している
- **何が起きるか:** `"a\n"` がヒント id として通る。include の `"git\n"` は解決できず、分かりにくい警告になる。
  JSON Schema(ECMA の正規表現)は同じ値を拒否するので、「検証器が通すものは Schema も通す」という約束にも反する。
- **修正方針:** `fullmatch` か `\Z` を使い、定数を 1 つにまとめる。

### 🟢-8 JSON Schema が、検証器の通す入力を拒否する
- **場所**
  - `src/wayhint/schema.py:118-119` `"width": {"type": ["integer", "string"]}`。実際には float も通る(`models.py:51`)。
  - `schema.py:59-60, 70` `["object", "null"]`。検証器は `wayland: []` や `process: ""` を、偽の値として黙って
    通す(`yaml_store.py:361-362` `node.get(desktop_key) or {}`)。
  - `schema.py:89` `version: {"const": 1}`。`yaml_store.py:515` は `True == 1` なので `version: true` を通す。
- **修正方針:** width / height は `number` に広げる。match と version は、検証器の側で型を明示的に確かめて拒否する。

### 🟢-9 `match.wayland` と `match.wayfire` を両方書くと、wayfire が黙って無視される
- **場所:** `src/wayhint/yaml_store.py:360` `desktop_key = "wayland" if "wayland" in node else "wayfire"`
  (`sheet_check.py:36` も常に `match.wayland` と表示する)
- **修正方針:** 両方あるときはエラーにする。

### 🟢-10 gen-protocol が、失敗しうる処理の前に生成物を空にする
- **場所:** `scripts/gen-protocol:7-40` `{ printf …; python3 -c '…' <…; } > src/wayhint/context/_wlr_foreign_toplevel.py`
- **何が起きるか:** リダイレクトが先に追跡ファイルを空にする。scanner の出力名が違ったり、インラインの
  スクリプトが例外を出したりすると、ヘッダ 4 行だけのファイルが残る。終了コードは非 0 になるが、作業ツリーは壊れる。
- **修正方針:** `$tmp` の中に書き、全部成功してから `mv` する。

### 🟢-11 setup-terminals の書き換えが、空白や改行コードまで変える
- **場所**
  - `scripts/setup-terminals:342-343` `parts = command.split()` / `" ".join([str(wrapper), *parts[1:]])`(`rewrite_exec` の 249 / 264 も同様)
  - `scripts/setup-terminals:386-389` `original.splitlines()` → `"\n".join(...)`
- **何が起きるか:** TERMINALS.md は「コマンドの先頭の語だけを置き換え、空白などはそのまま」と言うが、実際には次のように変わる。
  - `foot -e sh -c 'echo  x'` の引用部分の連続空白が詰まる。
  - CRLF のファイルが LF になる。
  - `\x0c` などの改行扱いの文字も `\n` になる。
- **修正方針:** 先頭の語の範囲だけを置き換える。読み込みは `newline=''`、分割は `keepends` にして、元の改行を保つ。

### 🟢-12 `HeadlessSession(width=, height=)` を受け取るが使わない
- **場所:** `tools/headless.py:122-123, 132`: `self.width, self.height = width, height` の後、どこでも使っていない。
- **何が起きるか:** GUI テストは 1280×720 を渡し、その値を前提に判定している。たまたまバックエンドの既定と
  同じなので通っているだけで、別の値を渡すと黙って違う寸法で測る。
- **修正方針:** 出力のモードに反映するか引数を無くす。最低でも、既定と等しいことを assert する。

### 🟢-13 `missing()` が、セッションで起動するプログラムを全部は確かめていない
- **場所:** `tools/headless.py:105-107` `TOOLS = ("grim", "magick")` とコンポジタだけ。`dbus-daemon`(:418)と
  `foot`(:506)は確かめていない。
- **何が起きるか:** これらが無いと、GUI テストが理由付きの skip にならず、`FileNotFoundError` で落ちる。
- **修正方針:** 2 つを要件の確認に加える。

### 🟢-14 古いコメント・docstring
- **場所**
  - `scripts/check-gui:7`「see tests/headless.py」。セッションの本体は `tools/headless.py` にある。
  - `tools/demo/review.py:13-14`「The captions are not in the stills」。`__main__.py:367` は、両方の録画にあれば
    字幕付きの `stills/` を比べる。
- **修正方針:** 文言を実装に合わせる。

### 🟢-15 `set_language` が開いているフォームを訳し直さない
- **場所:** `src/wayhint/ui/window.py:385-400`(`_form_title` と `_form_note` を再適用していない)
- **修正方針:** 言語を変えたら、開いているフォームのラベルも再適用する。

### 🟢-16 出力の名前は wl_output v4 からしか取れない
- **場所:** `src/wayhint/context/wayland.py:178`(`name` は v4 から)、`:47`
- **何が起きるか:** v3 までしか出さないコンポジタでは、すべての出力の `info()` が None になり、配置は黙って既定の
  モニタになる。
- **修正方針:** v4 未満では名前以外の手がかり(geometry と make / model)で出力を対応付けるか、ログで知らせる。

---

## ❓ 要確認

### ❓-1 閉じた toplevel の proxy を破棄していない(レビュー担当 2 人の判断が分かれた)
- **場所**
  - `src/wayhint/context/wayland.py:197` `handle.dispatcher["closed"] = lambda h: _discard(self.toplevels, t)`
  - `close()`(`:152-153`)は、一覧に残った handle しか破棄しない。
- **理由:** 1 人は、closed になった handle が disconnect 後に GC され、DECISIONS 0010 の解放済みメモリ参照になると
  指摘した。もう 1 人は、`Display.disconnect` が WeakSet で持つ生きている子を破棄するので守られている、と判断した。
  プロトコル上は、closed を受けたクライアントが destroy すべきもの。
- **確かめ方:** pywayland の `Display.disconnect` の実装を読む。closed の直後に GC を強制する再現を試す。

### ❓-2 `toggle` の編集・検索分岐が、ウィンドウの表示状態で決めている
- **場所:** `src/wayhint/daemon.py:337-347`(`if self.window.is_shown()`)と、遅延適用の `daemon.py:1112-1115`(`GLib.idle_add`)
- **理由:** ワークスペースを移った直後の `Super+h` の結果が、`toggle` と idle の `_apply_workspace` の実行順で変わる
  可能性がある。`toggle_action` の docstring が避けるべきだと言っている判定のしかた。メインループが実際に
  この順で入れ替わるかは確かめていない。
- **確かめ方:** `self._shown_key == key and is_shown()` で判定するか、コマンドを処理する前に保留中の
  ワークスペース変更を適用し、GUI テストで見る。

### ❓-3 `context --shown` の応答が 4096 バイトを超えうる
- **場所**
  - `src/wayhint/daemon.py:436-441`(`explain_filters` と include の id 一覧)
  - `src/wayhint/ipc.py:135-136`(`reply too large`)
  - `daemon.py:1194-1197`(ノンブロッキングの `sendall` の `BlockingIOError` を `OSError` として握り潰す)
- **理由:** include が多いかタグの一覧が長い構成で、CLI が「daemon が落ちている」と同じ扱い(exit 2)になる。
  実際の構成での大きさは測っていない。

### ❓-4 `_focus_list` でフォーカスが実際に移るか
- **場所:** `src/wayhint/ui/window.py:663` `if not (row or self._list).grab_focus(): self.set_focus(None)`
- **理由:** DESIGN §2 は、EXCLUSIVE の layer surface では `grab_focus()` が真を返してもフォーカスが付かないと
  記録している。そのとき `get_focus()` が検索ボックスを返すと、`c` がコピーではなく文字として入る。check-gui で確かめる。

### ❓-5 再読み込みで、`d` の確認待ちが解除されるか
- **場所:** `src/wayhint/ui/window.py:909` `self._list.remove_all()`、`:1110-1111`(`_on_row_selected` が `_delete_pending` を消す)
- **理由:** 選択中の行を remove したときに GtkListBox が `row-selected(None)` を出すなら、「もう一度 d」の表示が
  残ったまま、次の `d` がまた確認になる。GTK の内部は読んでいない。

### ❓-6 古い wl_output に `release` を送る
- **場所:** `src/wayhint/context/wayland.py:158` `out.proxy.release if hasattr(out.proxy, "release") else out.proxy.destroy`
- **理由:** 生成されたクラスは常に `release` を持つので、v3 未満で bind した出力にも v3 の要求を送る。
  pywayland が版を確かめるかどうか次第で、終了時のプロトコルエラーになる。

### ❓-7 demo の点滅の安定判定が短すぎるかもしれない
- **場所:** `tools/demo/capture.py:25-28, 76-77`(7 回 × `STEP` 0.08 秒を「1.2 秒周期の約 2 倍」としている)
- **理由:** sleep だけなら 0.56 秒。grim の 1 回あたりの所要時間が約 0.25 秒あって初めて成り立つ。
  速いマシンでは、点滅中のキャレットが「安定」と判定されうる。grim の所要時間は測っていない。

### ❓-8 `toplevel()` が部分一致で待つ
- **場所:** `tools/headless.py:521` `if app_id in self.wayhint("context")`
- **理由:** app_id が context の出力の別の場所に含まれる(`foo` と `foot` など)と、窓がまだアクティブになる前に
  戻りうる。context の出力の形式は確かめていない。

### ❓-9 headless の runtime ディレクトリを再利用すると、古いソケットで起動待ちが通る
- **場所**
  - `tools/headless.py:150` `… / f"wh-{tag or 't'}{os.getpid()}"`
  - `:202` `mkdir(…, exist_ok=True)`
  - `:470` `if path.exists(): return`
- **理由:** 同じプロセスで前のセッションがディレクトリを残していると(:266-272)、次のセッションは古い
  `wayland-0` / `wayhint.sock` を見て即座に「起動した」とみなす。前のセッションが残す条件が要る。

### ❓-10 Schema の `learned` が `"format": "date"`
- **場所:** `src/wayhint/schema.py:49`
- **理由:** 検証器は任意の文字列と datetime を通す(`yaml_store.py:384-385`)。yaml-language-server が `format` を
  強制するなら、`learned: 2026-09` がエディタでだけエラーになる。強制するかは確かめていない。

### ❓-11 ↑ で検索ボックスに戻ると、入力が全選択される
- **場所:** `src/wayhint/ui/window.py:643-644`(`_focus_search` が `select_region(0, -1)` する)
- **理由:** 次の 1 文字でフィルタ全体が置き換わる。DECISIONS 0039 の意図かどうかが不明で、HOTKEYS にも記述が無い。

---

## 読んでいない範囲

- `tools/demo/scenario.py` の大部分(spawn の argv 解析 195-264 だけ読んだ)、`tools/demo/storyboard.py`、
  `showcase.py`、`names.py`。
- `i18n.py` は通読しただけで、カタログと `ui/` の呼び出しの対応は突き合わせていない。
- `matcher.py` のタイムアウトとキャッシュの経路、`selection.explain_filters` と CLI 出力の対応。
- 生成物の `context/_wlr_foreign_toplevel.py`。

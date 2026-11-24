# Agent Limits

Codex、Claude Code、Antigravity CLI（agy） の使用枠をターミナルで一覧できます。Python 3.10 以降の標準ライブラリを使います。

```sh
./agent-limits
./agent-limits claude
./agent-limits agy
./agent-limits codex --history
```

PATH から使うには、実行ファイル `agent-limits` へのシンボリックリンクを作成してください。一覧では取得に失敗したサービスがあっても残りを表示し、終了コード 1 を返します。

### ブラウザで最新の利用枠を見る

```sh
./agent-limits --serve
```

起動中に http://127.0.0.1:8765/ を開いてください。ページを開くたび、または再読み込みするたびに、Mac 上で Codex の利用枠とリセットチケット、Antigravity の利用枠を照会します。Claude はステータスラインが最後に記録した値と取得からの経過時間を表示します。停止は Ctrl+C です。

### 利用枠をHTMLファイルに保存する

```sh
./agent-limits --html .work/limits.html
open -a "Brave Browser" .work/limits.html
```

HTMLは生成時点のスナップショットです。サーバーは不要です。同じコマンドで再生成し、ブラウザを再読み込みすると更新されます。
バーが利用枠の残量、縦線が期間の残りです。週間枠の縦線は毎日09:00〜20:00（JST）の利用時間を基準にします。Codex のリセットチケットには利用可能枚数と各チケットの失効日時を表示します。
取得に失敗した項目があっても、取得できた分を保存して終了コード1を返します。

### Claude Code

Claude Code のステータスラインが受け取る JSON から、5時間枠・週間枠の使用率とリセット時刻を記録します。既存スクリプトが `input=$(cat)` で入力を読む場合は、その直後に次を追加してください。

```sh
printf '%s' "$input" | agent-limits capture-claude
```

対応プランで最初の応答を受け取ると記録が始まります。表示には取得からの経過時間を添え、リセットを過ぎた枠は除きます。キャッシュは `${XDG_CACHE_HOME:-~/.cache}/agent-limits/claude.json` に保存します。同じ OS ユーザーで複数アカウントを使う場合は、最後に記録したアカウントの値が表示されます。

### Antigravity CLI (agy)

ログイン済みの `agy` を PATH に置いてください。`agent-limits agy` は `agy -p /usage` を実行し、モデルグループごとの利用枠、残量、リセット時刻を表示します。従来の `agent-limits gemini` も同じ表示になります。

### Codex

`coli` は Codex の現在の使用量と reset credits を `~/.codex/auth.json` の認証情報で取得し、terminal 向けに併記するコマンドです。

## セットアップ

Python 3.10以降を使用します。依存はPython標準ライブラリのみです。
OSに `Asia/Tokyo` のタイムゾーンデータが必要です（macOSでは標準搭載）。
ChatGPTアカウントでCodexにログインし、`~/.codex/auth.json` に `tokens.access_token` が保存されている環境を対象とします。
APIキー認証のみの環境には対応していません。

```sh
ghq get kazuhideoki/agent-limits
cd "$(ghq root)/github.com/kazuhideoki/agent-limits"
python3 codex_limits.py
```

ghqを使わない場合は `git clone https://github.com/kazuhideoki/agent-limits.git` で取得できます。
dotfilesの `coli` ラッパーは、このghq配置先の `codex_limits.py` を実行します。
単独で `coli` コマンドを使う場合は、PATH内のディレクトリにスクリプトへのリンクを作成してください。

## Usage

```sh
coli
coli --history
```

terminal 出力では、5時間枠/週間枠のリセットまでの残り時間率、現在の使用量の残量パーセント、reset credit の期限までの残日数をバーで表示します。
5時間枠の残り時間率は、リセット直後が `100%`、リセット直前が `0%` に近くなります。
週間枠の `利用時間残り (09-20)` は、JSTの毎日09:00〜20:00だけを対象に、リセットまでに残っている利用時間の割合を表示します。20:00〜翌09:00の間は減少しません。
reset credit は既定で `30日 = 100%` として計算します。
reset credit の残り時間は1時間未満になると分単位で表示し、1日未満の行を warning、2時間未満の行を error の色で表示します。

既定では次の endpoint を呼び出します。

```text
https://chatgpt.com/backend-api/codex/usage
https://chatgpt.com/backend-api/wham/rate-limit-reset-credits
```

`codex/usage` は非公開の ChatGPT backend endpoint です。
`auth.json` の token は出力しません。

`--history` を付けると、通常表示の後に過去7日間の使用枠履歴を追加します。
週間枠・5時間枠を期間ごとに分け、使用率とモデル・利用元・タスクの発生元・ターンの起動契機の内訳をバーで表示します。
各バーの100%は、その期間の使用上限です。内訳は使用量全体に対する構成比ではありません。
日時はJSTで表示し、概算・一部未集計・集計未完了・不明な使用率を区別します。
週間枠は暦週ではなくAPIの期間に従います。5時間枠が返らない場合は「履歴なし」と表示します。

履歴取得先は `https://chatgpt.com/backend-api/wham/usage/plan_limit_history?days=7` です。
`--history` 指定時だけGETし、404は「未提供」、その他の取得エラーは通常表示を残したうえでエラー終了します。
履歴はリアルタイムとは限らないため、表示される集計時刻を確認してください。

認証ファイルの場所は `~/.codex/auth.json` に固定です。
`CODEX_HOME` を変えている環境では、現在の実装はその変更を参照しません。

## APIと認証情報

OpenAI公式のツールではありません。非公開のChatGPT backend endpointを使用するため、
APIや認証形式の変更で動かなくなる可能性があります。
認証トークンはローカルファイルから読み、上記のChatGPT endpointへ送信します。
使用量とreset creditsの取得はGETのみで、creditの使用や購入は行いません。
認証ファイルや実際のAPIレスポンスを、このリポジトリへ追加しないでください。

## 検証

認証情報やネットワーク接続なしで実行できます。

```sh
python3 -m unittest discover -v
```

元の実装は [dotfiles](https://github.com/kazuhideoki/dotfiles) の `scripts/codex_limits` から移植しました。

## ライセンス

MIT。詳細は [LICENSE](LICENSE) を参照してください。

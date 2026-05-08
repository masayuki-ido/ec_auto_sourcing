"""
data/instagram/next_post.json から GitHub Issue 本文(Markdown)を生成して標準出力に書き出す。
generate_daily.yml から呼び出す想定。

環境変数:
  REPO         : owner/name 形式 (例: masayuki-ido/ec_auto_sourcing)
  ITEM_ID      : 商品ID
  GENERATED_AT : 自動生成タイムスタンプ表示用文字列

使い方:
  REPO=... ITEM_ID=... GENERATED_AT=... python scripts/build_issue_body.py > body.md
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEXT_POST_PATH = ROOT / "data" / "instagram" / "next_post.json"


def main() -> None:
    repo = os.environ["REPO"]
    item_id = os.environ["ITEM_ID"]
    generated_at = os.environ["GENERATED_AT"]
    regen_url = f"https://github.com/{repo}/actions/workflows/generate_daily.yml"
    next_json_url = f"https://github.com/{repo}/blob/main/data/instagram/next_post.json"

    post = json.loads(NEXT_POST_PATH.read_text(encoding="utf-8"))
    caption = post.get("caption", "")
    images = post.get("image_urls") or (
        [post["image_url"]] if post.get("image_url") else []
    )
    cover_url = images[0] if images else ""

    image_lines = []
    for i, url in enumerate(images, 1):
        label = f"{i}枚目 (表紙)" if i == 1 else f"{i}枚目"
        image_lines.append(f"{i}. [{label}]({url})")
    image_list = "\n".join(image_lines) if image_lines else "(画像なし)"

    body = f"""## 表紙プレビュー
![cover]({cover_url})

## キャプション (タップして全文コピー)
```
{caption}
```

## 投稿手順 (Instagram アプリで手動投稿)
1. 下記の画像URLをスマホで開いて、写真アプリに **長押し → 写真に追加** で全部保存
2. Instagram アプリで「**+**」→「**投稿**」→ 1枚目から順に選択(複数選択でカルーセル)
3. 編集画面で上記キャプションを貼り付け
4. 場所/タグは任意 → 「**シェア**」

> Graph API 経由の自動投稿は停止中。手動投稿のみで運用しています。

## 画像 (この順でカルーセルに追加)
{image_list}

## 候補を作り直す
👉 [Re-run Generate Daily Post Candidate]({regen_url})

## 詳細
- [next_post.json]({next_json_url})
- 自動生成: {generated_at}
"""
    sys.stdout.write(body)


if __name__ == "__main__":
    main()

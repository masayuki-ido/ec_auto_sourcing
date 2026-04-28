---
description: 商品リッチ化をN件実行（デフォルト5）
allowed-tools: Bash
---

引数 `$ARGUMENTS` で件数を受け取り（未指定なら5）、商品リッチ化を実行する。

実行:
```bash
cd ~/Desktop/ec_auto_sourcing && source .venv/bin/activate && AUTO=1 python enrich_products.py --count ${ARGS:-5}
```

完了したら成功件数とリッチ化された商品名一覧を報告する。失敗があれば `enrich_skip.json` に自動追加されている。

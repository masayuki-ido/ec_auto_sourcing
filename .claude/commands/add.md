---
description: Netseaから商品をN件追加（デフォルト10）
allowed-tools: Bash
---

引数 `$ARGUMENTS` で件数を受け取り（未指定なら10）、Netsea検索で商品を追加する。

実行:
```bash
cd ~/Desktop/ec_auto_sourcing && source .venv/bin/activate && AUTO=1 python add_netsea.py --count ${ARGS:-10}
```

完了したら `/tmp/add_netsea.log` の最後の `完了:` 行を抽出して結果を報告する。

**重要**: `add_five.py`（Taobao）は絶対に使わない。必ず `add_netsea.py`。

---
description: 商品追加(Netsea)→リッチ化を順次実行。引数: 追加件数 リッチ化件数（デフォルト 10 5）
allowed-tools: Bash
---

引数 `$ARGUMENTS` を「追加件数 リッチ化件数」の2つで受け取る（未指定なら 10 5）。
1) Netsea検索で商品を追加
2) 完了後、商品リッチ化を実行

順次バックグラウンドで実行（時間がかかるため）:
```bash
cd ~/Desktop/ec_auto_sourcing && source .venv/bin/activate
ADD_N=$(echo "$ARGUMENTS" | awk '{print ($1=="" ? 10 : $1)}')
ENRICH_N=$(echo "$ARGUMENTS" | awk '{print ($2=="" ? 5 : $2)}')
AUTO=1 python add_netsea.py --count $ADD_N > /tmp/add_netsea.log 2>&1
AUTO=1 python enrich_products.py --count $ENRICH_N > /tmp/enrich.log 2>&1
```

両方完了したら、追加件数とリッチ化件数・商品名一覧を報告する。

**重要**: 商品追加は必ず `add_netsea.py`。`add_five.py`（Taobao）は使わない。

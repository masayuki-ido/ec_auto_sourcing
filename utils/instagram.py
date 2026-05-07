"""
Instagram Graph API ユーティリティ

主な機能:
  - アクセストークンの動作確認
  - 画像投稿（単一画像 / カルーセル）
  - 過去投稿のインサイト取得

トークン運用方針:
  IG_ACCESS_TOKEN は graph.instagram.com 系の長期ユーザートークン(60日)を使用する。
  自動refresh(ig_refresh_token のスクリプト呼び出し)は廃止。データセンターIPからの
  自動化シグナル化を避けるため、Meta Business Suite 経由で **手動ローテーション** する運用に
  統一する。期限が近づいたら check_instagram.py で残日数を確認し、新トークンを再発行 → .env を上書き。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.instagram.com/{GRAPH_API_VERSION}"


def _token() -> str:
    token = os.getenv("IG_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("IG_ACCESS_TOKEN が .env に設定されていません")
    return token


def _user_id() -> str:
    user_id = os.getenv("IG_USER_ID")
    if not user_id:
        raise RuntimeError("IG_USER_ID が .env に設定されていません")
    return user_id


def _validate_image_url(image_url: str) -> None:
    """publish前に画像URLが有効(200 + Content-Type: image/*)か確認。
    無効なURLでメディアコンテナ作成を試みると Meta側でエラーが発生し、
    繰り返されると自動化アクティビティ判定の材料になり得るため事前チェックする。
    """
    try:
        res = requests.head(image_url, timeout=15, allow_redirects=True)
    except requests.RequestException as e:
        raise RuntimeError(f"画像URLにアクセスできません: {image_url} ({e})")
    if res.status_code != 200:
        raise RuntimeError(f"画像URLが {res.status_code} を返しました: {image_url}")
    ctype = res.headers.get("content-type", "")
    if not ctype.startswith("image/"):
        raise RuntimeError(f"画像URLのContent-Typeが画像ではありません ({ctype}): {image_url}")


def whoami() -> dict[str, Any]:
    """トークンの所有者情報を取得して動作確認"""
    res = requests.get(
        f"{GRAPH_BASE}/me",
        params={
            "fields": "id,username,account_type",
            "access_token": _token(),
        },
        timeout=30,
    )
    res.raise_for_status()
    return res.json()


def publish_image(image_url: str, caption: str) -> str:
    """単一画像を投稿し、投稿IDを返す

    Instagram Graph APIは2段階:
      1. メディアコンテナ作成（image_url + captionを登録）
      2. publish 呼び出しで実際にフィードに公開
    """
    user_id = _user_id()
    token = _token()

    _validate_image_url(image_url)

    # 1. メディアコンテナ作成
    create_res = requests.post(
        f"{GRAPH_BASE}/{user_id}/media",
        data={
            "image_url": image_url,
            "caption": caption,
            "access_token": token,
        },
        timeout=60,
    )
    create_res.raise_for_status()
    container_id = create_res.json()["id"]
    logger.info(f"メディアコンテナ作成: {container_id}")

    # コンテナ準備完了まで待機（数秒〜数十秒）
    _wait_container_ready(container_id, token)

    # 2. publish
    publish_res = requests.post(
        f"{GRAPH_BASE}/{user_id}/media_publish",
        data={
            "creation_id": container_id,
            "access_token": token,
        },
        timeout=60,
    )
    publish_res.raise_for_status()
    media_id = publish_res.json()["id"]
    logger.info(f"投稿成功: {media_id}")
    return media_id


def publish_carousel(image_urls: list[str], caption: str) -> str:
    """複数画像をカルーセル投稿（最大10枚）"""
    if not 2 <= len(image_urls) <= 10:
        raise ValueError("カルーセル投稿は2〜10枚の画像が必要です")

    user_id = _user_id()
    token = _token()

    for url in image_urls:
        _validate_image_url(url)

    # 各画像を子コンテナとして作成
    children_ids = []
    for idx, url in enumerate(image_urls):
        res = requests.post(
            f"{GRAPH_BASE}/{user_id}/media",
            data={
                "image_url": url,
                "is_carousel_item": "true",
                "access_token": token,
            },
            timeout=60,
        )
        if not res.ok:
            logger.error(f"子コンテナ作成失敗 idx={idx} url={url} status={res.status_code} body={res.text}")
            res.raise_for_status()
        children_ids.append(res.json()["id"])

    for cid in children_ids:
        _wait_container_ready(cid, token)

    # 親（カルーセル）コンテナ作成
    parent_res = requests.post(
        f"{GRAPH_BASE}/{user_id}/media",
        data={
            "media_type": "CAROUSEL",
            "children": ",".join(children_ids),
            "caption": caption,
            "access_token": token,
        },
        timeout=60,
    )
    parent_res.raise_for_status()
    parent_id = parent_res.json()["id"]
    _wait_container_ready(parent_id, token)

    publish_res = requests.post(
        f"{GRAPH_BASE}/{user_id}/media_publish",
        data={
            "creation_id": parent_id,
            "access_token": token,
        },
        timeout=60,
    )
    publish_res.raise_for_status()
    media_id = publish_res.json()["id"]
    logger.info(f"カルーセル投稿成功: {media_id}")
    return media_id


def _wait_container_ready(container_id: str, token: str, max_wait: int = 60) -> None:
    """コンテナが FINISHED になるまで待機"""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        res = requests.get(
            f"{GRAPH_BASE}/{container_id}",
            params={"fields": "status_code", "access_token": token},
            timeout=30,
        )
        res.raise_for_status()
        status = res.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"コンテナ処理エラー: {container_id}")
        time.sleep(2)
    raise TimeoutError(f"コンテナが {max_wait} 秒以内に準備完了しませんでした")


def fetch_recent_media(limit: int = 25) -> list[dict[str, Any]]:
    """直近の投稿を取得（インサイト分析用）"""
    res = requests.get(
        f"{GRAPH_BASE}/{_user_id()}/media",
        params={
            "fields": "id,caption,media_type,permalink,timestamp,like_count,comments_count",
            "limit": limit,
            "access_token": _token(),
        },
        timeout=30,
    )
    res.raise_for_status()
    return res.json().get("data", [])


def fetch_media_insights(media_id: str) -> dict[str, Any]:
    """個別投稿のインサイトを取得"""
    res = requests.get(
        f"{GRAPH_BASE}/{media_id}/insights",
        params={
            "metric": "reach,impressions,saved,total_interactions",
            "access_token": _token(),
        },
        timeout=30,
    )
    res.raise_for_status()
    return res.json()

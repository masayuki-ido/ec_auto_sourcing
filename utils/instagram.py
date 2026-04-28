"""
Instagram Graph API ユーティリティ

主な機能:
  - アクセストークンの動作確認 / 有効期限取得
  - 長期トークンへの更新（リフレッシュ）
  - 画像投稿（単一画像 / カルーセル）
  - 過去投稿のインサイト取得
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
GRAPH_ROOT = "https://graph.instagram.com"


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


def refresh_long_lived_token() -> dict[str, Any]:
    """長期トークンを更新（60日延長）。長期トークンは発行から24時間以上経過後にリフレッシュ可能"""
    res = requests.get(
        f"{GRAPH_ROOT}/refresh_access_token",
        params={
            "grant_type": "ig_refresh_token",
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

    # 各画像を子コンテナとして作成
    children_ids = []
    for url in image_urls:
        res = requests.post(
            f"{GRAPH_BASE}/{user_id}/media",
            data={
                "image_url": url,
                "is_carousel_item": "true",
                "access_token": token,
            },
            timeout=60,
        )
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

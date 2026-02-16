"""
WebRTC Server Main

QEMU D-Bus DisplayをWebRTCでブラウザに配信
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from aiohttp import web
import aiohttp_cors

# パス設定
sys.path.insert(0, str(Path(__file__).parent.parent))

from dbus.display_capture import DisplayCapture
from server.signaling import SignalingServer
from server.input_handler import InputHandler

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# aiortcとasynciのログを抑制（大量のDEBUGログを防ぐ）
logging.getLogger('aiortc').setLevel(logging.WARNING)
logging.getLogger('asyncio').setLevel(logging.WARNING)
logging.getLogger('aiohttp.access').setLevel(logging.WARNING)
logging.getLogger('aioice').setLevel(logging.WARNING)
logging.getLogger('aioice.ice').setLevel(logging.WARNING)
logging.getLogger('dasbus').setLevel(logging.WARNING)
logging.getLogger('dasbus.connection').setLevel(logging.WARNING)
logging.getLogger('dbus.listener').setLevel(logging.WARNING)
logging.getLogger('dbus.dmabuf_gl').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def _contains_placeholder(value: str) -> bool:
    lower = value.lower()
    return (
        "your_turn_host" in lower
        or "turn_public_ip_or_dns" in lower
        or "your_public_ip" in lower
        or "<" in value
        or ">" in value
    )


def _normalize_urls(urls):
    if isinstance(urls, str):
        return [urls]
    if isinstance(urls, list) and all(isinstance(item, str) for item in urls):
        return urls
    return None


def _load_webrtc_config_payload():
    """
    WebRTC ICE設定を環境変数から読み込む。

    QEMU_WEBRTC_ICE_SERVERS:
      JSON配列文字列。例:
      [{"urls":"stun:stun.l.google.com:19302"},
       {"urls":["turn:turn.example.com:3478?transport=udp","turn:turn.example.com:3478?transport=tcp"],
        "username":"user","credential":"pass"}]

    QEMU_WEBRTC_ICE_TRANSPORT_POLICY:
      "all" または "relay"（省略時は未指定）

    代替（JSONを使わない設定）:
      QEMU_WEBRTC_TURN_HOST
      QEMU_WEBRTC_TURN_USERNAME (default: webrtc)
      QEMU_WEBRTC_TURN_CREDENTIAL
      QEMU_WEBRTC_TURN_TRANSPORTS (default: udp,tcp)
      QEMU_WEBRTC_STUN_URL (optional)
    """
    config = {"iceServers": []}
    errors = []

    ice_servers_raw = os.environ.get("QEMU_WEBRTC_ICE_SERVERS", "").strip()
    if ice_servers_raw:
        try:
            parsed = json.loads(ice_servers_raw)
            if isinstance(parsed, list):
                config["iceServers"] = parsed
            else:
                errors.append("QEMU_WEBRTC_ICE_SERVERS must be a JSON array")
        except json.JSONDecodeError as e:
            errors.append(f"Invalid QEMU_WEBRTC_ICE_SERVERS JSON: {e}")
    else:
        turn_host = os.environ.get("QEMU_WEBRTC_TURN_HOST", "").strip()
        turn_username = os.environ.get("QEMU_WEBRTC_TURN_USERNAME", "webrtc").strip()
        turn_credential = os.environ.get("QEMU_WEBRTC_TURN_CREDENTIAL", "").strip()
        turn_transports = os.environ.get("QEMU_WEBRTC_TURN_TRANSPORTS", "udp,tcp").strip()
        stun_url = os.environ.get("QEMU_WEBRTC_STUN_URL", "").strip()

        if turn_host:
            if _contains_placeholder(turn_host):
                errors.append("QEMU_WEBRTC_TURN_HOST contains placeholder text")
            if not turn_credential:
                errors.append("QEMU_WEBRTC_TURN_CREDENTIAL is required when QEMU_WEBRTC_TURN_HOST is set")
            transports = [item.strip() for item in turn_transports.split(",") if item.strip()]
            if not transports:
                transports = ["udp", "tcp"]
            turn_urls = [f"turn:{turn_host}:3478?transport={transport}" for transport in transports]
            if stun_url:
                config["iceServers"].append({"urls": stun_url})
            config["iceServers"].append({
                "urls": turn_urls,
                "username": turn_username,
                "credential": turn_credential,
            })

    policy = os.environ.get("QEMU_WEBRTC_ICE_TRANSPORT_POLICY", "").strip()
    if policy in {"all", "relay"}:
        config["iceTransportPolicy"] = policy
    elif policy:
        errors.append("QEMU_WEBRTC_ICE_TRANSPORT_POLICY must be 'all' or 'relay'")

    # ICE server content validation
    for idx, server in enumerate(config.get("iceServers", [])):
        if not isinstance(server, dict):
            errors.append(f"iceServers[{idx}] must be object")
            continue
        normalized_urls = _normalize_urls(server.get("urls"))
        if normalized_urls is None:
            errors.append(f"iceServers[{idx}].urls must be string or string[]")
            continue
        if any(_contains_placeholder(url) for url in normalized_urls):
            errors.append(f"iceServers[{idx}].urls contains placeholder text")
        if any(url.startswith("turn:") for url in normalized_urls):
            if not server.get("username"):
                errors.append(f"iceServers[{idx}] turn URL requires username")
            if not server.get("credential"):
                errors.append(f"iceServers[{idx}] turn URL requires credential")

    payload = {
        "iceServers": config.get("iceServers", []),
        "errors": errors,
    }
    if "iceTransportPolicy" in config:
        payload["iceTransportPolicy"] = config["iceTransportPolicy"]

    if errors:
        for err in errors:
            logger.error(f"WebRTC config error: {err}")
    return payload


async def wait_for_initial_frame(display_capture):
    """初期フレームをバックグラウンドで待機"""
    try:
        while True:
            frame = await display_capture.get_frame()
            if frame is not None:
                logger.info(f"✓ Initial frame received: {frame.shape}")
                break
            await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"Error waiting for initial frame: {e}")


async def index(request):
    """インデックスページ"""
    content = Path(__file__).parent.parent / 'client' / 'index.html'
    return web.FileResponse(content)


async def webrtc_config(request):
    """WebRTC ICE設定を返す"""
    return web.json_response(request.app["webrtc_config"])


async def main():
    """メイン処理"""
    logger.info("=" * 80)
    logger.info("QEMU WebRTC Server")
    logger.info("=" * 80)
    print()
    
    # 1. DisplayCapture初期化
    logger.info("1. Initializing DisplayCapture...")
    display_capture = DisplayCapture()
    
    # D-Bus接続
    if not await display_capture.connect():
        logger.error("Failed to connect to QEMU D-Bus")
        return
    
    logger.info(f"✓ Connected to QEMU: {display_capture.width}x{display_capture.height}")
    
    # DisplayListener登録
    if not await display_capture.setup_listener():
        logger.error("Failed to setup DisplayListener")
        return
    
    logger.info("✓ DisplayListener registered")
    print()
    
    # 2. WebRTCサーバー起動（先に起動）
    logger.info("2. Starting WebRTC server...")
    
    signaling = SignalingServer(display_capture)
    input_handler = InputHandler(display_capture)
    
    # aiohttp Application作成
    app = web.Application()
    app["webrtc_config"] = _load_webrtc_config_payload()
    app.router.add_get('/', index)
    app.router.add_get('/webrtc-config', webrtc_config)
    app.router.add_post('/offer', signaling.handle_offer)
    app.router.add_post('/mouse', input_handler.handle_mouse)
    app.router.add_post('/keyboard', input_handler.handle_keyboard)
    app.router.add_static('/client', Path(__file__).parent.parent / 'client')
    
    # CORS設定
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods="*",
        )
    })
    
    # サーバー起動
    runner = web.AppRunner(app)
    await runner.setup()
    
    # ポート8081を使用（8080は使用中）
    site = web.TCPSite(runner, '0.0.0.0', 8081)
    await site.start()
    
    logger.info("=" * 80)
    logger.info("✓ Server running on http://localhost:8081")
    logger.info("=" * 80)
    logger.info("Open http://localhost:8081 in your browser")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 80)
    print()
    
    # 初期フレームを取得（サーバー起動後にバックグラウンドで待機）
    logger.info("Waiting for initial frame in background...")
    asyncio.create_task(wait_for_initial_frame(display_capture))
    
    try:
        # サーバー実行
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
    finally:
        # クリーンアップ
        logger.info("Cleaning up...")
        await signaling.cleanup_all()
        display_capture.disconnect()
        await runner.cleanup()
        logger.info("✓ Shutdown complete")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

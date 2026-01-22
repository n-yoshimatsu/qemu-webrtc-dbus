"""
WebRTC Server Main

QEMU D-Bus DisplayをWebRTCでブラウザに配信
"""

import asyncio
import logging
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
    app.router.add_get('/', index)
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

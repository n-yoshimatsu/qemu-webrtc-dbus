"""
GLib + asyncio統合ヘルパー

GLibのメインループをasyncioと統合して、D-Busコールバックを受信可能にする
"""

import asyncio
import logging
from gi.repository import GLib

logger = logging.getLogger(__name__)


class GLibAsyncioIntegration:
    """
    GLibメインループとasyncioを統合
    
    D-BusコールバックがGLibメインループで処理されるため、
    asyncioと並行して動かす必要がある
    """
    
    def __init__(self):
        self.main_loop = GLib.MainLoop()
        self.running = False
        
    async def run_glib_loop(self):
        """
        GLibメインループをasyncioタスクとして実行
        """
        logger.info("Starting GLib main loop in background...")
        
        self.running = True
        
        # GLibメインループを別スレッドで実行
        import threading
        
        def run_loop():
            logger.info("GLib main loop thread started")
            self.main_loop.run()
            logger.info("GLib main loop thread stopped")
        
        thread = threading.Thread(target=run_loop, daemon=True)
        thread.start()
        
        logger.info("✓ GLib main loop running in background")
        
        # asyncioで待機し続ける（終了まで）
        while self.running:
            await asyncio.sleep(0.1)
    
    def stop(self):
        """GLibメインループ停止"""
        logger.info("Stopping GLib main loop...")
        self.running = False
        if self.main_loop.is_running():
            self.main_loop.quit()

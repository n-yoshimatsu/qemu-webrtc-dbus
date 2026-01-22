"""
Input Handler for WebRTC

ブラウザからの入力イベントを受信してQEMUに送信
"""

import logging
import time
from aiohttp import web

logger = logging.getLogger(__name__)


class InputHandler:
    """マウス/キーボード入力ハンドラ"""
    
    def __init__(self, display_capture):
        """
        Args:
            display_capture: DisplayCaptureインスタンス
        """
        self.display_capture = display_capture
        self._mouse_move_count = 0  # Phase 2: 測定用カウンター
        logger.info("InputHandler initialized")
    
    async def handle_mouse(self, request: web.Request) -> web.Response:
        """
        マウスイベントを処理
        
        Args:
            request: マウスイベントデータを含むPOSTリクエスト
        
        Returns:
            JSONレスポンス
        """
        try:
            # === Phase 2: 測定開始 ===
            t_receive = time.time()
            
            data = await request.json()
            t1 = time.time()
            
            event_type = data.get('type')
            
            if event_type == 'move':
                # マウス移動
                x = int(data.get('x', 0))
                y = int(data.get('y', 0))
                
                t2 = time.time()
                self.display_capture.send_mouse_move(x, y)
                t3 = time.time()
                
                # 100回に1回だけログ（頻繁すぎるため）
                self._mouse_move_count += 1
                if self._mouse_move_count % 100 == 0:
                    logger.info(f"[PERF-MOUSE] #{self._mouse_move_count}: 受信→JSON解析={(t1-t_receive)*1000:.1f}ms, D-Bus送信={(t3-t2)*1000:.1f}ms, 総時間={(t3-t_receive)*1000:.1f}ms")
                
            elif event_type == 'press':
                # マウスボタン押下
                button = int(data.get('button', 1))
                
                t2 = time.time()
                self.display_capture.send_mouse_press(button)
                t3 = time.time()
                
                logger.info(f"Mouse press: {button}")
                logger.info(f"[PERF-MOUSE] Press: D-Bus送信={(t3-t2)*1000:.1f}ms")
                
            elif event_type == 'release':
                # マウスボタン解放
                button = int(data.get('button', 1))
                
                t2 = time.time()
                self.display_capture.send_mouse_release(button)
                t3 = time.time()
                
                logger.info(f"Mouse release: {button}")
                logger.info(f"[PERF-MOUSE] Release: D-Bus送信={(t3-t2)*1000:.1f}ms")
            
            return web.json_response({'status': 'ok'})
            
        except Exception as e:
            logger.error(f"Mouse event error: {e}")
            return web.json_response({'error': str(e)}, status=500)
    
    async def handle_keyboard(self, request: web.Request) -> web.Response:
        """
        キーボードイベントを処理
        
        Args:
            request: キーボードイベントデータを含むPOSTリクエスト
        
        Returns:
            JSONレスポンス
        """
        try:
            data = await request.json()
            event_type = data.get('type')
            keycode = int(data.get('keycode', 0))
            
            if event_type == 'keydown':
                # キー押下
                self.display_capture.send_key_press(keycode)
                logger.info(f"Key down: {keycode}")
                
            elif event_type == 'keyup':
                # キー解放
                self.display_capture.send_key_release(keycode)
                logger.info(f"Key up: {keycode}")
            
            return web.json_response({'status': 'ok'})
            
        except Exception as e:
            logger.error(f"Keyboard event error: {e}")
            return web.json_response({'error': str(e)}, status=500)

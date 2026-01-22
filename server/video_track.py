"""
QEMU Video Track for WebRTC

DisplayCaptureから取得したフレームをWebRTCで配信
"""

import asyncio
import logging
import fractions
import time
import os
from typing import Optional
from av import VideoFrame
from aiortc import VideoStreamTrack

logger = logging.getLogger(__name__)


class QEMUVideoTrack(VideoStreamTrack):
    """
    QEMU DisplayCaptureからWebRTCへのビデオストリーム
    """
    
    def __init__(self, display_capture, fps: int = 30, start_time: Optional[float] = None):
        """
        Args:
            display_capture: DisplayCaptureインスタンス
            fps: フレームレート（デフォルト30fps）
            start_time: 計測開始時刻（Noneの場合は現在時刻）
        """
        super().__init__()
        self.display_capture = display_capture
        self.fps = fps
        self.frame_interval = 1.0 / fps
        self.start_time = start_time or time.time()
        self._first_frame_logged = False
        
        # フレームカウンター
        self.frame_count = 0
        
        # 最後のフレーム（新しいフレームがない場合に再送）
        self.last_frame = None
        
        # タイムスタンプ管理
        self.time_base = fractions.Fraction(1, 90000)  # WebRTC標準
        self.pts = 0
        self.pts_increment = 90000 // fps  # 90kHz / fps
        
        logger.info(f"QEMUVideoTrack initialized: {fps}fps")
    
    async def recv(self) -> VideoFrame:
        """
        次のビデオフレームを取得
        
        WebRTCクライアントから呼ばれる
        
        Returns:
            av.VideoFrame
        """
        try:
            # DisplayCaptureから新しいフレームを取得（タイムアウト付き）
            frame_data = await asyncio.wait_for(
                self.display_capture.get_frame(),
                timeout=self.frame_interval
            )
            
            # 新しいフレームが来た場合のみ更新
            if frame_data is not None:
                self.last_frame = frame_data
            
        except asyncio.TimeoutError:
            # タイムアウト：新しいフレームがない
            pass
        
        # 新しいフレームがない場合は最後のフレームを使用
        if frame_data is None:
            frame_data = self.last_frame
        
        # フレームデータがない場合は黒画面
        source = "new"
        if frame_data is None:
            # 警告を削除（頻繁すぎるため）
            width = self.display_capture.width or 1280
            height = self.display_capture.height or 800
            # 最新フレームがある場合は即時に使う
            latest = await self.display_capture.get_latest_frame_copy()
            if latest is not None:
                frame_data = latest
                self.last_frame = latest
                source = "latest"
            else:
                import numpy as np
                frame_data = np.zeros((height, width, 3), dtype=np.uint8)
                source = "black"
        elif frame_data is self.last_frame:
            source = "cached"
        
        # パフォーマンス改善：解像度を1/2にダウンサンプリング（高速）
        # 環境変数で無効化可能: QEMU_WEBRTC_DOWNSAMPLE=0
        if os.environ.get("QEMU_WEBRTC_DOWNSAMPLE", "0") != "0":
            frame_data = frame_data[::2, ::2]
        
        # av.VideoFrameに変換
        frame = VideoFrame.from_ndarray(frame_data, format='rgb24')
        
        # タイムスタンプ設定
        frame.pts = self.pts
        frame.time_base = self.time_base
        
        # 次のフレーム用にPTSを更新
        self.pts += self.pts_increment
        self.frame_count += 1

        if not self._first_frame_logged:
            elapsed_ms = (time.time() - self.start_time) * 1000
            logger.info(f"First frame sent after {elapsed_ms:.1f}ms (source={source})")
            self._first_frame_logged = True
        
        # ログ削除（パフォーマンス改善）
        
        return frame
    
    def stop(self):
        """トラック停止"""
        super().stop()
        logger.info(f"QEMUVideoTrack stopped: {self.frame_count} frames sent")


class MockVideoTrack(VideoStreamTrack):
    """
    テスト用のモックビデオトラック
    QEMUが利用できない場合に使用
    """
    
    def __init__(self, fps: int = 10):
        super().__init__()
        self.fps = fps
        self.frame_interval = 1.0 / fps
        self.pts = 0
        self.pts_increment = int(fractions.Fraction(1, fps) * 90000)  # 90kHz clock
        self.time_base = fractions.Fraction(1, 90000)
        self.frame_count = 0
        
        logger.info(f"MockVideoTrack initialized: {fps}fps")
    
    async def recv(self) -> VideoFrame:
        """
        テスト用のフレームを生成
        
        Returns:
            av.VideoFrame: テストパターン
        """
        await asyncio.sleep(self.frame_interval)
        
        # テストパターン生成（チェックボード）
        import numpy as np
        height, width = 480, 640
        frame_data = np.zeros((height, width, 3), dtype=np.uint8)
        
        # チェックボードパターン
        for y in range(0, height, 40):
            for x in range(0, width, 40):
                color = (255, 255, 255) if ((x // 40) + (y // 40)) % 2 == 0 else (0, 0, 0)
                frame_data[y:y+40, x:x+40] = color
        
        # フレーム番号を表示
        import cv2
        cv2.putText(frame_data, f"Frame: {self.frame_count}", (10, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        
        # av.VideoFrameに変換
        frame = VideoFrame.from_ndarray(frame_data, format='rgb24')
        
        # タイムスタンプ設定
        frame.pts = self.pts
        frame.time_base = self.time_base
        
        # 次のフレーム用にPTSを更新
        self.pts += self.pts_increment
        self.frame_count += 1
        
        return frame
    
    def stop(self):
        """トラック停止"""
        super().stop()
        logger.info(f"MockVideoTrack stopped: {self.frame_count} frames sent")

"""
QEMU Video Track for WebRTC

DisplayCaptureから取得したフレームをWebRTCで配信
"""

import asyncio
import logging
import fractions
from typing import Optional
from av import VideoFrame
from aiortc import VideoStreamTrack

logger = logging.getLogger(__name__)


class QEMUVideoTrack(VideoStreamTrack):
    """
    QEMU DisplayCaptureからWebRTCへのビデオストリーム
    """
    
    def __init__(self, display_capture, fps: int = 30):
        """
        Args:
            display_capture: DisplayCaptureインスタンス
            fps: フレームレート（デフォルト30fps）
        """
        super().__init__()
        self.display_capture = display_capture
        self.fps = fps
        self.frame_interval = 1.0 / fps
        
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
        if frame_data is None:
            # 警告を削除（頻繁すぎるため）
            width = self.display_capture.width or 1280
            height = self.display_capture.height or 800
            import numpy as np
            frame_data = np.zeros((height, width, 3), dtype=np.uint8)
        
        # パフォーマンス改善：解像度を1/2にダウンサンプリング（高速）
        # [::2, ::2] = 2ピクセルごとにサンプリング → 1/4のピクセル数
        frame_data = frame_data[::2, ::2]
        
        # av.VideoFrameに変換
        frame = VideoFrame.from_ndarray(frame_data, format='rgb24')
        
        # タイムスタンプ設定
        frame.pts = self.pts
        frame.time_base = self.time_base
        
        # 次のフレーム用にPTSを更新
        self.pts += self.pts_increment
        self.frame_count += 1
        
        # ログ削除（パフォーマンス改善）
        
        return frame
    
    def stop(self):
        """トラック停止"""
        super().stop()
        logger.info(f"QEMUVideoTrack stopped: {self.frame_count} frames sent")

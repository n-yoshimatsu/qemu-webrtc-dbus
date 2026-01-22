"""
Frame Buffer - Phase 3A: 画像データ変換

QEMUのD-Bus DisplayからのPIXMAN形式データをRGB画像に変換し、
フレームバッファとして管理する。
"""

import numpy as np
import logging
from typing import Optional, Tuple
from PIL import Image

logger = logging.getLogger(__name__)


# PIXMANフォーマット定義
# QEMU D-Bus Displayで使用される主要なフォーマット
PIXMAN_x8r8g8b8 = 537923896  # 32bpp, xRGB (最も一般的)
PIXMAN_a8r8g8b8 = 537923848  # 32bpp, ARGB
PIXMAN_r8g8b8   = 540029088  # 24bpp, RGB


class FrameBuffer:
    """
    フレームバッファ管理
    
    - Scanout（全画面更新）とUpdate（部分更新）を処理
    - PIXMAN形式からRGB形式に変換
    - WebRTC用のフレーム提供
    """
    
    def __init__(self, width: int = 640, height: int = 480):
        """
        初期化
        
        Args:
            width: 画面幅
            height: 画面高さ
        """
        self.width = width
        self.height = height
        
        # RGB形式のフレームバッファ (height, width, 3)
        self.buffer = np.zeros((height, width, 3), dtype=np.uint8)
        
        # 統計情報
        self.scanout_count = 0
        self.update_count = 0
        
        logger.info(f"FrameBuffer initialized: {width}x{height}")
    
    def resize(self, width: int, height: int):
        """
        画面サイズ変更
        
        Args:
            width: 新しい幅
            height: 新しい高さ
        """
        if width != self.width or height != self.height:
            logger.info(f"Resizing buffer: {self.width}x{self.height} -> {width}x{height}")
            self.width = width
            self.height = height
            self.buffer = np.zeros((height, width, 3), dtype=np.uint8)
    
    def _decode_pixman_data(
        self, 
        data: bytes, 
        width: int, 
        height: int, 
        stride: int, 
        pixman_format: int
    ) -> np.ndarray:
        """
        PIXMANデータをRGB配列にデコード
        
        Args:
            data: PIXMANピクセルデータ
            width: 幅
            height: 高さ
            stride: 1行のバイト数
            pixman_format: PIXMANフォーマット
        
        Returns:
            RGB配列 (height, width, 3)
        """
        if pixman_format == PIXMAN_x8r8g8b8 or pixman_format == PIXMAN_a8r8g8b8:
            # 32bpp: xRGB または ARGB
            # バイト順: B G R X (リトルエンディアン)
            
            # データを2D配列に変換
            # stride行ごとに分割し、width * 4バイトのみ使用
            pixels = np.frombuffer(data, dtype=np.uint8)
            
            # stride != width * 4 の場合を考慮
            if stride == width * 4:
                # 高速パス
                pixels = pixels.reshape((height, width, 4))
            else:
                # パディングがある場合
                rows = []
                for y in range(height):
                    row_start = y * stride
                    row_end = row_start + (width * 4)
                    row = pixels[row_start:row_end].reshape((width, 4))
                    rows.append(row)
                pixels = np.array(rows)
            
            # BGR → RGB変換 (B=0, G=1, R=2, X=3)
            rgb = pixels[:, :, [2, 1, 0]]  # R, G, B
            
            return rgb.astype(np.uint8)
        
        elif pixman_format == PIXMAN_r8g8b8:
            # 24bpp: RGB
            pixels = np.frombuffer(data, dtype=np.uint8)
            
            if stride == width * 3:
                rgb = pixels.reshape((height, width, 3))
            else:
                rows = []
                for y in range(height):
                    row_start = y * stride
                    row_end = row_start + (width * 3)
                    row = pixels[row_start:row_end].reshape((width, 3))
                    rows.append(row)
                rgb = np.array(rows)
            
            return rgb.astype(np.uint8)
        
        else:
            raise ValueError(f"Unsupported PIXMAN format: {pixman_format}")
    
    def update_full(
        self, 
        width: int, 
        height: int, 
        stride: int, 
        pixman_format: int, 
        data: bytes
    ):
        """
        Scanout: 全画面更新
        
        Args:
            width: 画像幅
            height: 画像高さ
            stride: 1行のバイト数
            pixman_format: PIXMANフォーマット
            data: ピクセルデータ
        """
        # サイズ変更が必要な場合
        if width != self.width or height != self.height:
            self.resize(width, height)
        
        # PIXMANデータをデコード
        rgb = self._decode_pixman_data(data, width, height, stride, pixman_format)
        
        # バッファ全体を更新
        self.buffer[:] = rgb
        
        self.scanout_count += 1
        logger.debug(f"Scanout updated: {width}x{height}, format={pixman_format}")
    
    def update_partial(
        self, 
        x: int, 
        y: int, 
        width: int, 
        height: int, 
        stride: int, 
        pixman_format: int, 
        data: bytes
    ):
        """
        Update: 部分更新
        
        Args:
            x: 更新領域のX座標
            y: 更新領域のY座標
            width: 更新領域の幅
            height: 更新領域の高さ
            stride: 1行のバイト数
            pixman_format: PIXMANフォーマット
            data: ピクセルデータ
        """
        # 範囲チェック
        if x < 0 or y < 0 or x + width > self.width or y + height > self.height:
            logger.warning(
                f"Update out of bounds: ({x},{y}) {width}x{height} "
                f"buffer={self.width}x{self.height}"
            )
            return
        
        # PIXMANデータをデコード
        rgb = self._decode_pixman_data(data, width, height, stride, pixman_format)
        
        # バッファの一部を更新
        self.buffer[y:y+height, x:x+width] = rgb
        
        self.update_count += 1
        logger.debug(f"Update applied: ({x},{y}) {width}x{height}")
    
    def get_frame(self) -> np.ndarray:
        """
        現在のフレームを取得（WebRTC用）
        
        Returns:
            RGB配列のコピー (height, width, 3)
        """
        return self.buffer.copy()
    
    def save_frame(self, filename: str):
        """
        現在のフレームを画像ファイルとして保存（デバッグ用）
        
        Args:
            filename: 保存するファイル名 (例: "frame.png")
        """
        img = Image.fromarray(self.buffer, mode='RGB')
        img.save(filename)
        logger.info(f"Frame saved: {filename}")
    
    def get_stats(self) -> dict:
        """
        統計情報を取得
        
        Returns:
            統計情報の辞書
        """
        return {
            'width': self.width,
            'height': self.height,
            'scanout_count': self.scanout_count,
            'update_count': self.update_count,
        }

"""
Display Listener - QEMU D-Bus Listener実装

QEMUからの画面更新を受信する（GLib/Gio経由）
"""

import logging
import mmap
import numpy as np
import time

logger = logging.getLogger(__name__)


class DisplayListener:
    """
    QEMU Display Listener実装
    
    QEMUから画面更新を受信する
    GLib/Gioのmethod_call_handlerから呼ばれる
    """
    
    def __init__(self, capture_object):
        self.capture = capture_object
        self.current_width = 0
        self.current_height = 0
        self.current_stride = 0
        self.current_format = 0
        self.current_y0_top = True  # デフォルトは上から下
        self.shared_memory = None
        self.shared_fd = None
        
        logger.info("DisplayListener initialized")
    
    def Scanout(self, width, height, stride, pixman_format, data):
        """
        画面全体の更新（Pixmanフォーマット）
        
        Args:
            width: 幅（ピクセル）
            height: 高さ（ピクセル）
            stride: ストライド（バイト）
            pixman_format: Pixmanフォーマット
            data: 画像データ（バイト列）
        """
        try:
            # === Phase 2: 測定開始 ===
            t_receive = time.time()
            
            logger.info(f"Scanout: {width}x{height}, stride={stride}, format=0x{pixman_format:08x}")
            logger.info(f"[PERF] Scanout受信時刻: {t_receive:.6f}")
            
            self.current_width = width
            self.current_height = height
            self.current_stride = stride
            self.current_format = pixman_format
            
            # Pixman → RGB変換
            t1 = time.time()
            rgb_frame = self._convert_pixman_to_rgb(data, width, height, stride, pixman_format)
            t2 = time.time()
            
            logger.info(f"[PERF] RGB変換時間: {(t2-t1)*1000:.1f}ms")
            
            if rgb_frame is not None:
                logger.info(f"✓ RGB conversion successful: {rgb_frame.shape}")
                
                # キャプチャオブジェクトに画像を渡す
                t3 = time.time()
                self.capture.update_frame_from_listener(rgb_frame)
                t4 = time.time()
                
                logger.info(f"[PERF] update_frame時間: {(t4-t3)*1000:.1f}ms")
                logger.info(f"[PERF] Scanout総処理時間: {(t4-t_receive)*1000:.1f}ms")
                logger.info(f"✓ Frame sent to capture: {width}x{height}")
            else:
                logger.error("✗ RGB conversion returned None")
            
        except Exception as e:
            logger.error(f"Scanout error: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def Update(self, x, y, width, height, stride, pixman_format, data):
        """
        画面の部分更新
        
        Args:
            x, y: 更新位置
            width, height: 更新サイズ
            stride: ストライド
            pixman_format: Pixmanフォーマット  
            data: 更新データ
        """
        try:
            # === Phase 2: 測定 ===
            t_receive = time.time()
            
            # 部分更新データを変換
            t1 = time.time()
            rgb_patch = self._convert_pixman_to_rgb(data, width, height, stride, pixman_format)
            t2 = time.time()
            
            if rgb_patch is not None:
                # 既存フレームの該当領域を更新
                t3 = time.time()
                self.capture.update_frame_region(x, y, rgb_patch)
                t4 = time.time()
                
                # 100回に1回だけログ（頻繁すぎるため）
                if not hasattr(self, '_update_count'):
                    self._update_count = 0
                self._update_count += 1
                
                if self._update_count % 100 == 0:
                    logger.info(f"[PERF] Update #{self._update_count}: RGB変換={( t2-t1)*1000:.1f}ms, フレーム更新={(t4-t3)*1000:.1f}ms, 総時間={(t4-t_receive)*1000:.1f}ms")
            else:
                logger.error(f"Update RGB conversion returned None")
                
        except Exception as e:
            logger.error(f"Update error: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def ScanoutDMABUF(self, fd, width, height, stride, fourcc, modifier, y0_top):
        """
        DMA-BUF共有メモリでの画面更新（OpenGL使用時）
        
        Args:
            fd: DMA-BUFファイルディスクリプタ
            width, height: サイズ
            stride: ストライド（バイト）
            fourcc: Fourccフォーマット（例: 0x34324258 = XB24）
            modifier: DMA-BUFモディファイア
            y0_top: Y座標の向き（True=上から下）
        """
        try:
            logger.info("=" * 80)
            logger.info(f"🎯 ScanoutDMABUF called!")
            logger.info(f"   fd={fd}, size={width}x{height}, stride={stride}")
            logger.info(f"   fourcc=0x{fourcc:08x}, modifier={modifier}, y0_top={y0_top}")
            logger.info("=" * 80)
            
            self.current_width = width
            self.current_height = height
            self.current_stride = stride
            self.current_dmabuf_fd = fd
            self.current_fourcc = fourcc
            self.current_y0_top = y0_top  # y0_topを保存
            
            # 既存のマップをクリーンアップ
            if self.shared_memory is not None:
                self.shared_memory.close()
                self.shared_memory = None
            
            # DMA-BUFをmmap
            try:
                size = stride * height
                logger.info(f"Attempting to mmap DMA-BUF: fd={fd}, size={size}")
                
                self.shared_memory = mmap.mmap(fd, size, mmap.MAP_SHARED, mmap.PROT_READ)
                logger.info(f"✓ DMA-BUF mmap successful: {size} bytes")
                
                # 初回データ読み込み
                self._update_from_dmabuf(fourcc, y0_top)
                
            except Exception as mmap_err:
                logger.error(f"✗ DMA-BUF mmap failed: {mmap_err}")
                import traceback
                logger.error(traceback.format_exc())
            
        except Exception as e:
            logger.error(f"ScanoutDMABUF error: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def UpdateDMABUF(self, x, y, width, height):
        """
        DMA-BUFの部分更新通知
        
        Args:
            x, y: 更新位置
            width, height: 更新サイズ
        """
        try:
            logger.debug(f"UpdateDMABUF: ({x},{y}) {width}x{height}")
            
            if self.shared_memory is not None:
                # 保存されたy0_topを使用（デフォルトはTrue）
                y0_top = getattr(self, 'current_y0_top', True)
                self._update_from_dmabuf(self.current_fourcc, y0_top)
                
        except Exception as e:
            logger.error(f"UpdateDMABUF error: {e}")
    
    def ScanoutMap(self, handle, offset, width, height, stride, pixman_format):
        """
        共有メモリマップでの画面更新（Unix専用）
        
        Args:
            handle: 共有メモリのファイルディスクリプタ
            offset: オフセット
            width, height: サイズ
            stride: ストライド
            pixman_format: Pixmanフォーマット
        """
        try:
            logger.info(f"ScanoutMap: fd={handle}, {width}x{height}, offset={offset}, format=0x{pixman_format:08x}")
            
            self.current_width = width
            self.current_height = height
            self.current_stride = stride
            self.current_format = pixman_format
            
            # 既存のマップをクリーンアップ
            if self.shared_memory is not None:
                self.shared_memory.close()
            
            # 共有メモリをmmap
            size = stride * height
            self.shared_fd = handle
            self.shared_memory = mmap.mmap(handle, size + offset, mmap.MAP_SHARED, mmap.PROT_READ)
            
            # 初回データ読み込み
            self._update_from_shared_memory()
            
        except Exception as e:
            logger.error(f"ScanoutMap error: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def UpdateMap(self, x, y, width, height):
        """
        共有メモリマップの部分更新
        """
        try:
            logger.debug(f"UpdateMap: ({x},{y}) {width}x{height}")
            
            if self.shared_memory is not None:
                self._update_from_shared_memory()
                
        except Exception as e:
            logger.error(f"UpdateMap error: {e}")
    
    def Disable(self):
        """ディスプレイ無効化"""
        logger.info("Display disabled")
        
        if self.shared_memory is not None:
            self.shared_memory.close()
            self.shared_memory = None
    
    def MouseSet(self, x, y, on):
        """マウスカーソル位置設定（オプション）"""
        pass
    
    def CursorDefine(self, width, height, hot_x, hot_y, data):
        """カーソル形状定義（オプション）"""
        pass
    
    def _convert_pixman_to_rgb(self, data, width, height, stride, pixman_format):
        """
        Pixmanフォーマット → RGB変換（NumPyベクトル化版）
        
        Args:
            data: Pixmanデータ
            width, height: サイズ
            stride: ストライド
            pixman_format: Pixmanフォーマット値
            
        Returns:
            RGB NumPy配列 (height, width, 3)
        """
        try:
            t_start = time.time()
            
            # Pixmanフォーマット判定
            # 0x20020888 = PIXMAN_X8R8G8B8 = BGRX (little-endian)
            # 0x20028888 = PIXMAN_A8R8G8B8 = BGRA (little-endian)
            if pixman_format == 0x20020888 or pixman_format == 0x20028888:
                # NumPy配列として扱う（高速化）
                data_array = np.frombuffer(data, dtype=np.uint8)
                
                # reshape: (height, stride) → 各行から width*4 バイト取り出し → (height, width, 4)
                pixels = data_array.reshape(height, stride)[:, :width*4].reshape(height, width, 4)
                
                # BGRX/BGRA → RGB 変換
                rgb = pixels[:, :, [2, 1, 0]].copy()
                
                t_end = time.time()
                logger.info(f"[PERF-RGB] RGB変換合計: {(t_end-t_start)*1000:.1f}ms")
                
                return rgb
                
            else:
                logger.warning(f"Unsupported Pixman format: 0x{pixman_format:08x}")
                return None
                
        except Exception as e:
            logger.error(f"Pixman conversion error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def _update_from_shared_memory(self):
        """共有メモリから画像を読み込んで更新"""
        try:
            if self.shared_memory is None:
                return
            
            # 共有メモリからデータ読み込み
            size = self.current_stride * self.current_height
            data = self.shared_memory.read(size)
            
            # RGB変換
            rgb_frame = self._convert_pixman_to_rgb(
                data, 
                self.current_width, 
                self.current_height, 
                self.current_stride, 
                self.current_format
            )
            
            if rgb_frame is not None:
                self.capture.update_frame_from_listener(rgb_frame)
                
        except Exception as e:
            logger.error(f"Shared memory update error: {e}")
    
    def _update_from_dmabuf(self, fourcc, y0_top):
        """DMA-BUFから画像を読み込んで更新"""
        try:
            if self.shared_memory is None:
                return
            
            logger.info(f"Reading from DMA-BUF: fourcc=0x{fourcc:08x}, size={self.current_stride * self.current_height}, y0_top={y0_top}")
            
            # DMA-BUFからデータ読み込み
            size = self.current_stride * self.current_height
            self.shared_memory.seek(0)
            data = self.shared_memory.read(size)
            
            logger.info(f"✓ Read {len(data)} bytes from DMA-BUF")
            
            # Fourcc → RGB変換
            rgb_frame = self._convert_fourcc_to_rgb(
                data,
                self.current_width,
                self.current_height,
                self.current_stride,
                fourcc
            )
            
            if rgb_frame is not None:
                # y0_top=False の場合、画像を上下反転
                if not y0_top:
                    logger.info("⚠ y0_top=False detected, flipping image vertically")
                    rgb_frame = np.flipud(rgb_frame)
                
                # デバッグ: 2回目以降のフレーム（実際のコンテンツ）を保存
                if not hasattr(self, '_debug_saved') or not self._debug_saved:
                    # 黒画面でなければ保存
                    if rgb_frame.max() > 10:  # 完全に黒でなければ
                        from PIL import Image
                        debug_path = "/tmp/dmabuf_debug.png"
                        img = Image.fromarray(rgb_frame, 'RGB')
                        img.save(debug_path)
                        logger.info(f"🔍 DEBUG: Saved frame to {debug_path} (max pixel value: {rgb_frame.max()})")
                        self._debug_saved = True
                
                logger.info(f"✓ RGB conversion successful: {rgb_frame.shape}")
                self.capture.update_frame_from_listener(rgb_frame)
            else:
                logger.error("✗ RGB conversion failed")
                
        except Exception as e:
            logger.error(f"DMA-BUF update error: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _convert_fourcc_to_rgb(self, data, width, height, stride, fourcc):
        """
        Fourccフォーマット → RGB変換（最もシンプルな実装）
        
        Args:
            data: DMA-BUFデータ
            width, height: サイズ
            stride: ストライド（バイト）
            fourcc: Fourccフォーマット値
            
        Returns:
            RGB NumPy配列 (height, width, 3)
        """
        try:
            t_start = time.time()
            
            # Fourcc: 0x34324258 = "XB24" = BGRX (little-endian)
            # Fourcc: 0x34324241 = "AB24" = BGRA
            if fourcc == 0x34324258 or fourcc == 0x34324241:
                # 最もシンプルな方法：Pythonループで確実に処理
                logger.info(f"Converting {width}x{height}, stride={stride}, format=0x{fourcc:08x}")
                
                data_array = np.frombuffer(data, dtype=np.uint8)
                rgb = np.zeros((height, width, 3), dtype=np.uint8)
                
                for y in range(height):
                    row_offset = y * stride
                    for x in range(width):
                        pixel_offset = row_offset + x * 4
                        # BGRX/BGRA → RGB
                        rgb[y, x, 0] = data_array[pixel_offset + 2]  # R
                        rgb[y, x, 1] = data_array[pixel_offset + 1]  # G
                        rgb[y, x, 2] = data_array[pixel_offset + 0]  # B
                
                # デバッグ: 最初の5ピクセルを確認
                if height > 0 and width > 0:
                    logger.info(f"First 5 pixels RGB: {rgb[0, :5, :]}")
                    logger.info(f"Last 5 pixels RGB: {rgb[-1, -5:, :]}")
                
                t_end = time.time()
                logger.info(f"✓ Fourcc conversion complete: {(t_end-t_start)*1000:.1f}ms")
                return rgb
                
            else:
                logger.warning(f"Unsupported Fourcc format: 0x{fourcc:08x}")
                return None
                
        except Exception as e:
            logger.error(f"Fourcc conversion error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

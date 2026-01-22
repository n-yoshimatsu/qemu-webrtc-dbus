"""
Display Capture - D-Bus Complete Version

QEMUのD-Bus DisplayインターフェースからRegisterListener経由で画面を取得
"""

import asyncio
import logging
import socket
import numpy as np
from typing import Optional
from dasbus.connection import SessionMessageBus
from dasbus.error import DBusError

from .listener import DisplayListener
from .p2p_glib import P2PListenerServer
from .register_listener_helper import call_register_listener_with_fd
from .glib_asyncio import GLibAsyncioIntegration

logger = logging.getLogger(__name__)


class DisplayCapture:
    """
    D-Bus経由でQEMU画面をキャプチャし、入力イベントを送信
    """
    
    def __init__(self):
        """初期化"""
        self.bus = None
        self.vm_proxy = None
        self.console_proxy = None
        self.console_path = None
        
        # DisplayListener & P2P Server
        self.listener = None
        self.p2p_server = None
        
        # GLibメインループ統合
        self.glib_integration = None
        
        # asyncioループ（メインスレッドの）
        self.main_loop = None
        
        # 画面情報
        self.width = 640
        self.height = 480
        
        # フレーム管理
        self.current_frame: Optional[np.ndarray] = None
        self.frame_lock = asyncio.Lock()
        self.frame_event = asyncio.Event()
        
        # プロキシキャッシュ（入力用）
        self.mouse_proxy = None
        self.keyboard_proxy = None
        
        # ソケットオブジェクトを保持（GC対策）
        self.client_socket = None
        self.server_socket = None
        
        logger.info("DisplayCapture initialized")
    
    async def connect(self) -> bool:
        """
        QEMU D-Busに接続
        
        Returns:
            成功時True
        """
        try:
            logger.info("Connecting to D-Bus session bus...")
            
            # セッションバス接続
            self.bus = SessionMessageBus()
            
            # VM proxy取得
            logger.info("Getting VM proxy...")
            self.vm_proxy = self.bus.get_proxy(
                "org.qemu",
                "/org/qemu/Display1/VM",
                "org.qemu.Display1.VM"
            )
            
            # Console検出
            console_ids = self.vm_proxy.ConsoleIDs
            if not console_ids:
                logger.error("No consoles available")
                return False
            
            logger.info(f"Available consoles: {console_ids}")
            
            # 最初のコンソールを使用
            console_id = console_ids[0]
            self.console_path = f"/org/qemu/Display1/Console_{console_id}"
            
            logger.info(f"Using console: {self.console_path}")
            
            # Console proxy取得
            self.console_proxy = self.bus.get_proxy(
                "org.qemu",
                self.console_path,
                "org.qemu.Display1.Console"
            )
            
            # 画面サイズ取得
            self.width = self.console_proxy.Width
            self.height = self.console_proxy.Height
            
            logger.info(f"✓ D-Bus connected: {self.width}x{self.height}")
            
            # 入力プロキシを初期化
            self._init_input_proxies()
            
            return True
            
        except DBusError as e:
            logger.error(f"D-Bus connection failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Connection error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def _init_input_proxies(self):
        """入力用プロキシを初期化"""
        try:
            self.mouse_proxy = self.bus.get_proxy(
                "org.qemu",
                self.console_path,
                "org.qemu.Display1.Mouse"
            )
            logger.info("✓ Mouse proxy initialized")
            
            self.keyboard_proxy = self.bus.get_proxy(
                "org.qemu",
                self.console_path,
                "org.qemu.Display1.Keyboard"
            )
            logger.info("✓ Keyboard proxy initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize input proxies: {e}")
    
    async def setup_listener(self) -> bool:
        """
        RegisterListenerを呼び出し、DisplayListenerを登録
        
        GLib/Gioを使ったP2P D-Bus接続実装
        参考: qemu-display (Rust実装)
        
        Returns:
            成功時True
        """
        try:
            logger.info("=== Setting up RegisterListener (GLib/Gio implementation) ===")
            
            # メインスレッドのasyncioループを保存
            self.main_loop = asyncio.get_event_loop()
            
            # 1. DisplayListenerインスタンス作成
            self.listener = DisplayListener(self)
            logger.info("✓ DisplayListener instance created")
            
            # 2. UNIXソケットペア作成
            logger.info("Creating socket pair...")
            self.client_socket, self.server_socket = socket.socketpair(
                socket.AF_UNIX,
                socket.SOCK_STREAM
            )
            
            # ソケットバッファサイズを増やす（大きなUpdateメッセージ用）
            self.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16*1024*1024)  # 16MB
            self.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 16*1024*1024)  # 16MB
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16*1024*1024)  # 16MB
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 16*1024*1024)  # 16MB
            logger.info(f"✓ Socket pair created: client_fd={self.client_socket.fileno()}, server_fd={self.server_socket.fileno()}")
            
            # 3. 先にQEMUにRegisterListenerを呼び出す（QEMU側がサーバーになる）
            logger.info("Calling RegisterListener...")
            
            if not call_register_listener_with_fd(self.console_path, self.server_socket.fileno()):
                logger.error("RegisterListener call failed")
                return False
            
            logger.info("✓ RegisterListener called - QEMU is now waiting for connection")
            
            # 4. P2P D-Busクライアント接続（client_socketでQEMUに接続）
            logger.info("Creating P2P D-Bus client connection...")
            self.p2p_server = P2PListenerServer(self.listener)
            
            if not self.p2p_server.setup(self.client_socket):
                logger.error("✗ P2P client connection failed")
                return False
            
            logger.info("✓ P2P client connected to QEMU")
            
            # 5. GLibメインループを開始（D-Busコールバック受信のため）
            logger.info("Starting GLib main loop for D-Bus callbacks...")
            self.glib_integration = GLibAsyncioIntegration()
            
            # バックグラウンドタスクとして起動
            asyncio.create_task(self.glib_integration.run_glib_loop())
            
            # GLibループが起動するまで少し待つ
            await asyncio.sleep(0.5)
            
            logger.info("=== RegisterListener setup complete ===")
            logger.info("Waiting for frames from QEMU...")
            
            # SetUIInfo呼び出し - リフレッシュレート設定（Update/UpdateMapを有効化）
            logger.info("\nCalling SetUIInfo to enable screen updates...")
            try:
                # QEMUに60Hz更新を要求
                self.console_proxy.SetUIInfo(
                    0,  # width_mm (0 = not specified)
                    0,  # height_mm (0 = not specified)
                    0,  # xoff
                    0,  # yoff
                    self.width,   # width (pixels)
                    self.height   # height (pixels)
                )
                logger.info(f"✓ SetUIInfo called: {self.width}x{self.height}")
                logger.info("  This should trigger Update/UpdateMap callbacks")
            except Exception as e:
                logger.warning(f"SetUIInfo failed (may still work): {e}")
            
            return True
            
        except ImportError as e:
            logger.error(f"GLib/Gio not available: {e}")
            logger.error("Install: pip install PyGObject")
            return False
        except Exception as e:
            logger.error(f"setup_listener error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def update_frame_from_listener(self, rgb_frame: np.ndarray):
        """
        DisplayListenerからのフレーム更新（同期コールバック）
        
        GLibスレッドから呼ばれるため、メインスレッドのループを使う
        
        Args:
            rgb_frame: RGB形式のNumPy配列 (H, W, 3)
        """
        try:
            if self.main_loop is None:
                logger.error("Main asyncio loop not available")
                return
            
            # メインスレッドのループで実行
            asyncio.run_coroutine_threadsafe(
                self._async_update_frame(rgb_frame),
                self.main_loop
            )
        except Exception as e:
            logger.error(f"Frame update error: {e}")
    
    async def _async_update_frame(self, rgb_frame: np.ndarray):
        """非同期フレーム更新"""
        async with self.frame_lock:
            self.current_frame = rgb_frame
            self.frame_event.set()  # 待機中のget_frame()に通知
            # ログなし（頻繁すぎるため）
    
    def update_frame_region(self, x: int, y: int, rgb_patch: np.ndarray):
        """
        フレームの部分更新
        
        Args:
            x, y: 更新位置
            rgb_patch: RGB部分データ
        """
        try:
            # 初期フレームがない場合は黒画面を作成
            if self.current_frame is None:
                logger.info(f"Creating initial frame from first Update: {self.width}x{self.height}")
                self.current_frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            
            h, w = rgb_patch.shape[:2]
            self.current_frame[y:y+h, x:x+w] = rgb_patch
            self.frame_event.set()
            # ログなし（頻繁すぎるため）
        except Exception as e:
            logger.error(f"Frame region update error: {e}")
    
    async def get_frame(self) -> Optional[np.ndarray]:
        """
        VideoTrackへのフレーム提供
        
        新しいフレームが来た場合のみ返す。
        フレーム更新がない場合はNoneを返し、VideoTrackが前フレームを再送する。
        
        Returns:
            RGB NumPy配列、またはNone
        """
        # フレーム更新があったかチェック
        if self.frame_event.is_set():
            async with self.frame_lock:
                self.frame_event.clear()  # イベントをクリア
                if self.current_frame is not None:
                    return self.current_frame.copy()
        
        # 更新なし → Noneを返す（VideoTrackが前フレームを再送）
        return None
    
    # ========== 入力メソッド（ステップ3から継承） ==========
    
    def send_mouse_move(self, x: int, y: int):
        """マウス移動"""
        try:
            if self.mouse_proxy:
                self.mouse_proxy.SetAbsPosition(x, y)
                # ログなし（頻繁すぎるため）
        except Exception as e:
            logger.error(f"Mouse move error: {e}")
    
    def send_mouse_press(self, button: int):
        """マウスボタン押下"""
        try:
            if self.mouse_proxy:
                self.mouse_proxy.Press(button)
                logger.debug(f"Mouse press: {button}")
        except Exception as e:
            logger.error(f"Mouse press error: {e}")
    
    def send_mouse_release(self, button: int):
        """マウスボタン解放"""
        try:
            if self.mouse_proxy:
                self.mouse_proxy.Release(button)
                logger.debug(f"Mouse release: {button}")
        except Exception as e:
            logger.error(f"Mouse release error: {e}")
    
    def send_key_press(self, keycode: int):
        """キー押下"""
        try:
            if self.keyboard_proxy:
                self.keyboard_proxy.Press(keycode)
        except Exception as e:
            logger.error(f"Key press error: {e}")
    
    def send_key_release(self, keycode: int):
        """キー解放"""
        try:
            if self.keyboard_proxy:
                self.keyboard_proxy.Release(keycode)
        except Exception as e:
            logger.error(f"Key release error: {e}")
    
    def disconnect(self):
        """接続解除"""
        logger.info("Disconnecting...")
        
        # GLibループ停止
        if self.glib_integration:
            self.glib_integration.stop()
        
        # P2Pサーバークリーンアップ
        if self.p2p_server:
            self.p2p_server.cleanup()
        
        # Listener共有メモリクリーンアップ
        if self.listener and hasattr(self.listener, 'shared_memory'):
            if self.listener.shared_memory:
                self.listener.shared_memory.close()
        
        logger.info("✓ Disconnected")

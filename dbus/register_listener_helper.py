"""
RegisterListener呼び出しヘルパー（UnixFD対応）

dasbusはUnixFDListをサポートしていないため、GDBusを直接使用
"""

import logging
from gi.repository import Gio, GLib

logger = logging.getLogger(__name__)


def call_register_listener_with_fd(console_proxy_path, fd):
    """
    RegisterListenerをUnixFDで呼び出す
    
    Args:
        console_proxy_path: コンソールのD-Busパス（例: "/org/qemu/Display1/Console_0"）
        fd: ファイルディスクリプタ（int）
        
    Returns:
        成功時True
    """
    try:
        logger.info(f"Calling RegisterListener with FD={fd}")
        
        # セッションバス接続取得
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        
        # UnixFDListを作成
        fd_list = Gio.UnixFDList.new()
        fd_index = fd_list.append(fd)
        
        logger.info(f"UnixFDList created, FD index: {fd_index}")
        
        # RegisterListener呼び出し
        result = bus.call_with_unix_fd_list_sync(
            bus_name="org.qemu",
            object_path=console_proxy_path,
            interface_name="org.qemu.Display1.Console",
            method_name="RegisterListener",
            parameters=GLib.Variant("(h)", (fd_index,)),  # h = Unix FD
            reply_type=None,
            flags=Gio.DBusCallFlags.NONE,
            timeout_msec=-1,
            fd_list=fd_list,
            cancellable=None
        )
        
        logger.info("✓ RegisterListener called successfully")
        return True
        
    except Exception as e:
        logger.error(f"RegisterListener failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

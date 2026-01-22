"""
P2P D-Bus Connection Helper

dasbusを使ったP2P D-Bus接続のヘルパー
"""

import logging
import socket
from dasbus.server.container import DBusContainer
from dasbus.connection import AddressedMessageBus

logger = logging.getLogger(__name__)


def create_p2p_listener_server(listener_object, client_socket):
    """
    P2P D-Bus接続でDisplayListenerを公開
    
    Args:
        listener_object: DisplayListenerインスタンス
        client_socket: クライアント側のソケット
        
    Returns:
        DBusContainer（失敗時None）
    """
    try:
        # 方法1: AddressedMessageBusを使う
        # UNIXソケットのFDからアドレスを作成
        fd = client_socket.fileno()
        
        # D-Busアドレス文字列を作成
        # 注: dasbusがFDベースのアドレスをサポートしているか不明
        # 通常はunix:path=...形式
        
        logger.warning("P2P D-Bus implementation is experimental")
        logger.info(f"Attempting P2P connection with fd={fd}")
        
        # TODO: 実装方法を調査
        # オプション1: GLib/Gioを使う（より確実）
        # オプション2: dbus-pythonを使う
        # オプション3: dasbusの拡張機能を探す
        
        # 一時的にNoneを返す
        logger.error("P2P D-Bus not yet implemented")
        return None
        
    except Exception as e:
        logger.error(f"P2P connection error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def setup_listener_with_glib(listener_object, client_socket):
    """
    GLib/Gioを使ったP2P D-Bus接続（代替案）
    
    Args:
        listener_object: DisplayListenerインスタンス
        client_socket: クライアント側のソケット
        
    Returns:
        GDBusConnection（成功時）、None（失敗時）
    """
    try:
        # GLibが利用可能か確認
        from gi.repository import Gio, GLib
        
        logger.info("Using GLib for P2P D-Bus connection")
        
        # ソケットからGIOソケット作成
        fd = client_socket.fileno()
        gio_socket = Gio.Socket.new_from_fd(fd)
        
        # ソケット接続を作成
        socket_connection = Gio.SocketConnection.factory_create_connection(gio_socket)
        
        # D-Bus接続を確立
        connection = Gio.DBusConnection.new_sync(
            stream=socket_connection,
            guid=None,
            flags=Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT,
            observer=None,
            cancellable=None
        )
        
        logger.info("✓ P2P D-Bus connection established (GLib)")
        
        # Listenerインターフェースを登録
        # TODO: DisplayListenerをGDBusに登録する実装
        
        return connection
        
    except ImportError:
        logger.error("GLib not available, cannot use GLib method")
        return None
    except Exception as e:
        logger.error(f"GLib P2P connection error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

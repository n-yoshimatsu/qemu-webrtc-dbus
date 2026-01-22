"""
GLib/Gio P2P D-Bus Implementation - WITH DEBUG LOGGING

Key fix: CLIENT側ではGUID=Noneが必須
"""

import logging
import socket
import sys
from typing import Optional
from gi.repository import Gio, GLib

logger = logging.getLogger(__name__)


class P2PListenerServer:
    """P2P D-Bus接続でDisplayListenerを公開"""
    
    # DisplayListener D-Busインターフェース定義（基本）
    LISTENER_INTERFACE = """
    <!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
     "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
    <node>
      <interface name="org.qemu.Display1.Listener">
        <method name="Scanout">
          <arg type="u" name="width" direction="in"/>
          <arg type="u" name="height" direction="in"/>
          <arg type="u" name="stride" direction="in"/>
          <arg type="u" name="pixman_format" direction="in"/>
          <arg type="ay" name="data" direction="in">
            <annotation name="org.gtk.GDBus.C.ForceGVariant" value="true"/>
          </arg>
        </method>
        <method name="Update">
          <arg type="i" name="x" direction="in"/>
          <arg type="i" name="y" direction="in"/>
          <arg type="i" name="width" direction="in"/>
          <arg type="i" name="height" direction="in"/>
          <arg type="u" name="stride" direction="in"/>
          <arg type="u" name="pixman_format" direction="in"/>
          <arg type="ay" name="data" direction="in">
            <annotation name="org.gtk.GDBus.C.ForceGVariant" value="true"/>
          </arg>
        </method>
        <method name="ScanoutDMABUF">
          <arg type="h" name="fd" direction="in"/>
          <arg type="u" name="width" direction="in"/>
          <arg type="u" name="height" direction="in"/>
          <arg type="u" name="stride" direction="in"/>
          <arg type="u" name="fourcc" direction="in"/>
          <arg type="t" name="modifier" direction="in"/>
          <arg type="b" name="y0_top" direction="in"/>
        </method>
        <method name="UpdateDMABUF">
          <arg type="i" name="x" direction="in"/>
          <arg type="i" name="y" direction="in"/>
          <arg type="i" name="width" direction="in"/>
          <arg type="i" name="height" direction="in"/>
        </method>
        <method name="Disable">
        </method>
        <method name="MouseSet">
          <arg type="i" name="x" direction="in"/>
          <arg type="i" name="y" direction="in"/>
          <arg type="i" name="on" direction="in"/>
        </method>
        <method name="CursorDefine">
          <arg type="i" name="width" direction="in"/>
          <arg type="i" name="height" direction="in"/>
          <arg type="i" name="hot_x" direction="in"/>
          <arg type="i" name="hot_y" direction="in"/>
          <arg type="ay" name="data" direction="in">
            <annotation name="org.gtk.GDBus.C.ForceGVariant" value="true"/>
          </arg>
        </method>
        <property name="Interfaces" type="as" access="read"/>
      </interface>
    </node>
    """
    
    # Unix共有メモリインターフェース定義（別インターフェース）
    MAP_INTERFACE = """
    <!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
     "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
    <node>
      <interface name="org.qemu.Display1.Listener.Unix.Map">
        <method name="ScanoutMap">
          <arg type="h" name="handle" direction="in"/>
          <arg type="u" name="offset" direction="in"/>
          <arg type="u" name="width" direction="in"/>
          <arg type="u" name="height" direction="in"/>
          <arg type="u" name="stride" direction="in"/>
          <arg type="u" name="pixman_format" direction="in"/>
        </method>
        <method name="UpdateMap">
          <arg type="i" name="x" direction="in"/>
          <arg type="i" name="y" direction="in"/>
          <arg type="i" name="width" direction="in"/>
          <arg type="i" name="height" direction="in"/>
        </method>
      </interface>
    </node>
    """
    
    def __init__(self, listener_object):
        self.listener = listener_object
        self.connection: Optional[Gio.DBusConnection] = None
        self.registration_ids = []  # 複数のインターフェースを登録
        
    def _on_connection_closed(self, connection, remote_peer_vanished, error):
        """D-Bus接続が閉じられた時のハンドラ"""
        logger.warning(f"D-Bus connection closed! remote_peer_vanished={remote_peer_vanished}, error={error}")
        
    
    def _message_filter(self, connection, message, incoming):
        """全てのD-Busメッセージをログ出力"""
        if incoming:
            msg_type = message.get_message_type()
            type_name = {
                Gio.DBusMessageType.METHOD_CALL: "METHOD_CALL",
                Gio.DBusMessageType.METHOD_RETURN: "METHOD_RETURN",
                Gio.DBusMessageType.ERROR: "ERROR",
                Gio.DBusMessageType.SIGNAL: "SIGNAL"
            }.get(msg_type, f"UNKNOWN({msg_type})")
            
            logger.info(f"[FILTER] Incoming {type_name}")
            
            if msg_type == Gio.DBusMessageType.METHOD_CALL:
                member = message.get_member()
                interface = message.get_interface()
                path = message.get_path()
                logger.info(f"[FILTER]   Member: {member}")
                logger.info(f"[FILTER]   Interface: {interface}")
                logger.info(f"[FILTER]   Path: {path}")
                
                # ファイルディスクリプタがある場合
                unix_fd_list = message.get_unix_fd_list()
                if unix_fd_list:
                    fd_count = unix_fd_list.get_length()
                    logger.info(f"[FILTER]   FD count: {fd_count}")
                    
                # メッセージフィルター内で全メソッドを処理（PyGObject register_objectの回避策）
                try:
                    body = message.get_body()
                    handled = False
                    
                    if member == "ScanoutDMABUF":
                        logger.info("📥 ScanoutDMABUF")
                        if unix_fd_list and unix_fd_list.get_length() > 0 and body:
                            fd_index, width, height, stride, fourcc, modifier, y0_top = body.unpack()
                            actual_fd = unix_fd_list.get(fd_index)
                            self.listener.ScanoutDMABUF(actual_fd, width, height, stride, fourcc, modifier, y0_top)
                            handled = True
                    
                    elif member == "UpdateDMABUF":
                        if body:
                            x, y, width, height = body.unpack()
                            self.listener.UpdateDMABUF(x, y, width, height)
                            handled = True
                    
                    elif member == "CursorDefine":
                        logger.info("📥 CursorDefine")
                        if body:
                            width, height, hot_x, hot_y, data = body.unpack()
                            self.listener.CursorDefine(width, height, hot_x, hot_y, bytes(data))
                            handled = True
                    
                    elif member == "MouseSet":
                        if body:
                            x, y, on = body.unpack()
                            self.listener.MouseSet(x, y, on)
                            handled = True
                    
                    elif member == "Scanout":
                        logger.info("📥 Scanout")
                        if body:
                            width, height, stride, pixman_format, data = body.unpack()
                            self.listener.Scanout(width, height, stride, pixman_format, bytes(data))
                            handled = True
                    
                    elif member == "Update":
                        if body:
                            x, y, width, height, stride, pixman_format, data = body.unpack()
                            self.listener.Update(x, y, width, height, stride, pixman_format, bytes(data))
                            handled = True
                    
                    elif member == "Disable":
                        self.listener.Disable()
                        handled = True
                    
                    if handled:
                        # メソッドリターンを送信
                        reply = Gio.DBusMessage.new_method_reply(message)
                        connection.send_message(reply, Gio.DBusSendMessageFlags.NONE)
                        # メッセージを消費（ハンドラーに渡さない）
                        return None
                        
                except Exception as e:
                    logger.error(f"Filter handling error for {member}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
        return message
    
    def setup(self, client_socket) -> bool:
        """P2P D-Bus接続を確立し、Listenerインターフェースを公開"""
        try:
            logger.info("Setting up P2P D-Bus connection...")
            
            # 1. ソケットからGIOストリーム作成
            # GSocketConnectionを使用してUnixFD転送を有効化
            fd = client_socket.fileno()
            logger.info(f"Creating GIO stream from fd={fd}")
            
            # GSocketを作成（Unix domain socket）
            socket = Gio.Socket.new_from_fd(fd)
            io_stream = socket.connection_factory_create_connection()
            
            logger.info("✓ GIO socket connection created")
            
            # 2. P2P D-Bus接続確立（CLIENTモード）
            # DELAY_MESSAGE_PROCESSINGを使用して、準備が整うまでメッセージをキューに保持
            logger.info("Establishing P2P D-Bus connection as CLIENT...")
            
            self.connection = Gio.DBusConnection.new_sync(
                io_stream,
                None,
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.DELAY_MESSAGE_PROCESSING,
                None,
                None
            )
            logger.info("✓ P2P D-Bus connection established")
            
            # UnixFD転送サポート確認
            caps = self.connection.get_capabilities()
            UNIX_FD_PASSING = Gio.DBusCapabilityFlags.UNIX_FD_PASSING
            supports_unix_fd = bool(caps & UNIX_FD_PASSING)
            logger.info(f"Connection capabilities: {caps}")
            logger.info(f"  UNIX_FD_PASSING support: {supports_unix_fd}")
            
            if not supports_unix_fd:
                logger.warning("⚠️  WARNING: UnixFD transfer is NOT supported on this P2P connection!")
                logger.warning("   ScanoutDMABUF and ScanoutMap will NOT work!")
            
            # 接続クローズのシグナルをキャッチ
            self.connection.connect('closed', self._on_connection_closed)
            
            # メッセージフィルターを最初に登録（すべてのメッセージをキャッチするため）
            self.connection.add_filter(self._message_filter)
            logger.info("✓ Message filter registered (EARLY)")
            
            # 3. Listenerインターフェース登録（基本）
            logger.info("Registering Listener interface...")
            
            introspection_data = Gio.DBusNodeInfo.new_for_xml(self.LISTENER_INTERFACE)
            interface_info = introspection_data.interfaces[0]
            
            reg_id1 = self.connection.register_object(
                "/org/qemu/Display1/Listener",
                interface_info,
                self._handle_method_call,
                self._handle_get_property,
                None
            )
            self.registration_ids.append(reg_id1)
            logger.info(f"✓ Listener interface registered (id={reg_id1})")
            
            # 4. Unix.Mapインターフェース登録（共有メモリ用）
            # FIXME: 同じパスに2つのインターフェースを登録すると競合する
            # 一旦コメントアウトして基本インターフェースのみテスト
            logger.info("Skipping Unix.Map interface registration (testing)")
            # map_introspection = Gio.DBusNodeInfo.new_for_xml(self.MAP_INTERFACE)
            # map_interface_info = map_introspection.interfaces[0]
            # 
            # reg_id2 = self.connection.register_object(
            #     "/org/qemu/Display1/Listener",
            #     map_interface_info,
            #     self._handle_method_call,
            #     None,  # Unix.Mapにはプロパティなし
            #     None
            # )
            # self.registration_ids.append(reg_id2)
            # logger.info(f"✓ Unix.Map interface registered (id={reg_id2})")
            
            # 5. メッセージ処理を開始
            # QEMU側がRegisterListener完了後すぐにScanoutDmabufを送信するため、
            # インターフェース登録が完了した時点でメッセージ処理を開始する
            logger.info("Starting message processing...")
            self.connection.start_message_processing()
            logger.info("✓ Message processing started")
            
            logger.info("✓✓✓ P2P Listener server setup complete")
            return True
            
        except Exception as e:
            logger.error(f"P2P setup failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def _handle_get_property(self, connection, sender, object_path, interface_name,
                            property_name):
        """D-Busプロパティ取得ハンドラ"""
        logger.info(f"[PROP_HANDLER] Property: {property_name}, Interface: {interface_name}")
        # ログなし（頻繁すぎるため）
        try:
            if property_name == "Interfaces":
                # QEMUにUnix.Mapインターフェースのサポートを通知
                return GLib.Variant('as', ["org.qemu.Display1.Listener.Unix.Map"])
            else:
                logger.warning(f"Unknown property requested: {property_name}")
                return None
        except Exception as e:
            logger.error(f"Property get error ({property_name}): {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def _handle_method_call(self, connection, sender, object_path, interface_name,
                           method_name, parameters, invocation):
        """D-Busメソッド呼び出しハンドラ"""
        logger.info(f"[HANDLER] Method: {method_name}, Interface: {interface_name}")
        try:
            # Scanoutのみログ（重要）、Update/MouseSetはログなし（頻繁すぎる）
            
            if method_name == "Scanout":
                width, height, stride, pixman_format, data = parameters.unpack()
                logger.info(f"Scanout: {width}x{height}")
                self.listener.Scanout(width, height, stride, pixman_format, bytes(data))
                invocation.return_value(None)
                
            elif method_name == "Update":
                # ログなし（頻繁すぎるため）
                x, y, width, height, stride, pixman_format, data = parameters.unpack()
                self.listener.Update(x, y, width, height, stride, pixman_format, bytes(data))
                invocation.return_value(None)
                
            elif method_name == "ScanoutDMABUF":
                logger.info("📥 ScanoutDMABUF METHOD_CALL received!")
                unix_fd_list = invocation.get_message().get_unix_fd_list()
                if unix_fd_list and unix_fd_list.get_length() > 0:
                    fd_index, width, height, stride, fourcc, modifier, y0_top = parameters.unpack()
                    actual_fd = unix_fd_list.get(fd_index)
                    logger.info(f"ScanoutDMABUF: fd={actual_fd}, {width}x{height}, fourcc=0x{fourcc:08x}")
                    self.listener.ScanoutDMABUF(actual_fd, width, height, stride, fourcc, modifier, y0_top)
                    invocation.return_value(None)
                else:
                    logger.error("ScanoutDMABUF: No FD in message")
                    invocation.return_error_literal(
                        Gio.dbus_error_quark(),
                        Gio.DBusError.INVALID_ARGS,
                        "No file descriptor provided"
                    )
                
            elif method_name == "UpdateDMABUF":
                x, y, width, height = parameters.unpack()
                logger.debug(f"UpdateDMABUF: ({x},{y}) {width}x{height}")
                self.listener.UpdateDMABUF(x, y, width, height)
                invocation.return_value(None)
                
            elif method_name == "ScanoutMap":
                unix_fd_list = invocation.get_message().get_unix_fd_list()
                if unix_fd_list and unix_fd_list.get_length() > 0:
                    handle_index, offset, width, height, stride, pixman_format = parameters.unpack()
                    actual_fd = unix_fd_list.get(handle_index)
                    logger.info(f"ScanoutMap: fd={actual_fd}, {width}x{height}")
                    self.listener.ScanoutMap(actual_fd, offset, width, height, stride, pixman_format)
                    invocation.return_value(None)
                else:
                    logger.error("ScanoutMap: No FD in message")
                    invocation.return_error_literal(
                        Gio.dbus_error_quark(),
                        Gio.DBusError.INVALID_ARGS,
                        "No file descriptor provided"
                    )
                
            elif method_name == "UpdateMap":
                x, y, width, height = parameters.unpack()
                logger.info(f"UpdateMap: ({x},{y}) {width}x{height}")
                self.listener.UpdateMap(x, y, width, height)
                invocation.return_value(None)
                
            elif method_name == "Disable":
                logger.info("Disable")
                self.listener.Disable()
                invocation.return_value(None)
                
            elif method_name == "MouseSet":
                x, y, on = parameters.unpack()
                self.listener.MouseSet(x, y, on)
                invocation.return_value(None)
                
            elif method_name == "CursorDefine":
                width, height, hot_x, hot_y, data = parameters.unpack()
                self.listener.CursorDefine(width, height, hot_x, hot_y, bytes(data))
                invocation.return_value(None)
                
            else:
                logger.warning(f"Unknown method: {method_name}")
                invocation.return_error_literal(
                    Gio.dbus_error_quark(),
                    Gio.DBusError.UNKNOWN_METHOD,
                    f"Unknown method: {method_name}"
                )
                
        except Exception as e:
            logger.error(f"Method call error ({method_name}): {e}")
            import traceback
            logger.error(traceback.format_exc())
            invocation.return_error_literal(
                Gio.dbus_error_quark(),
                Gio.DBusError.FAILED,
                str(e)
            )
    
    def cleanup(self):
        """接続とリソースのクリーンアップ"""
        try:
            if self.registration_id and self.connection:
                self.connection.unregister_object(self.registration_id)
                self.registration_id = None
            if self.connection:
                self.connection.close_sync(None)
                self.connection = None
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

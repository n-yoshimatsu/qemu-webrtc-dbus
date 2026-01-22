# QEMU D-Bus Display 性能問題調査 - フェーズ4

## 概要

日付: 2026-01-21  
調査対象: QEMU D-Bus Display + WebRTC統合における画面転送問題  
フェーズ: ScanoutDMABUF受信問題の根本原因特定

---

## 前回（Phase 3）までの状況

### 確認できた事実

1. ✅ gl=on環境でQEMUは正常にScanoutDmabufを呼び出している
2. ✅ P2P D-Bus接続は確立されている（接続Capability確認済み）
3. ❌ ScanoutDmabufメッセージがクライアント側のハンドラーに届かない
4. ✅ メッセージフィルターではScanoutDMABUFを検出できる

### 仮説

- タイミング問題
- インターフェース登録の問題
- UnixFD転送の問題

---

## Phase 4 調査内容

### 1. UnixFD転送サポートの確認

**実施内容**: P2P接続のCapabilityフラグを確認

**コード追加** (`dbus/p2p_glib.py:174-187`):
```python
# UnixFD転送サポート確認
caps = self.connection.get_capabilities()
UNIX_FD_PASSING = Gio.DBusCapabilityFlags.UNIX_FD_PASSING
supports_unix_fd = bool(caps & UNIX_FD_PASSING)
logger.info(f"Connection capabilities: {caps}")
logger.info(f"  UNIX_FD_PASSING support: {supports_unix_fd}")
```

**結果**:
```
Connection capabilities: 1
UNIX_FD_PASSING support: True
```

✅ **UnixFD転送はサポートされている**

### 2. ScanoutDMABUFメッセージの到達確認

**ログ確認**:
```
[FILTER] Incoming METHOD_CALL
[FILTER]   Member: ScanoutDMABUF
[FILTER]   Interface: org.qemu.Display1.Listener
[FILTER]   Path: /org/qemu/Display1/Listener
[FILTER]   FD count: 1
```

✅ **ScanoutDMABUFメッセージは到達している**

### 3. ハンドラーが呼ばれない問題の発見

**確認したこと**:
```bash
grep "\[HANDLER\]" /tmp/client_register_test_v2.log
# 結果: 何も出力されない
```

**重大な発見**: 
- ScanoutDMABUFだけでなく、**すべてのメソッドでハンドラーが呼ばれていない**
- `_handle_method_call()`の先頭ログ `[HANDLER]` が全く出力されない
- メッセージフィルターには届くが、登録したハンドラーに渡されない

### 4. Unix.Map二重登録の可能性を調査

**仮説**: 同じパス`/org/qemu/Display1/Listener`に2つのインターフェースを登録している

**実施**: Unix.Mapインターフェースの登録をコメントアウト

**結果**: ❌ 問題は解決せず。ハンドラーは依然として呼ばれない

### 5. メッセージフィルター内で直接処理（決定的な証拠）

**実施内容**: メッセージフィルター内でScanoutDMABUFを直接処理

**コード** (`dbus/p2p_glib.py:140-175`):
```python
if member == "ScanoutDMABUF":
    # フィルター内で直接処理
    if unix_fd_list and unix_fd_list.get_length() > 0:
        body = message.get_body()
        fd_index, width, height, stride, fourcc, modifier, y0_top = body.unpack()
        actual_fd = unix_fd_list.get(fd_index)
        
        # Listenerを呼び出し
        self.listener.ScanoutDMABUF(actual_fd, width, height, stride, fourcc, modifier, y0_top)
        
        # メソッドリターンを送信
        reply = Gio.DBusMessage.new_method_reply(message)
        connection.send_message(reply, Gio.DBusSendMessageFlags.NONE)
        
        # メッセージを消費（ハンドラーに渡さない）
        return None
```

**結果**:
```
🎯 ScanoutDMABUF MESSAGE DETECTED IN FILTER!
🧪 ATTEMPTING TO HANDLE IN FILTER
📥 FILTER: ScanoutDMABUF received!
   fd=10, 1280x800, stride=5120
   fourcc=0x34324258, modifier=0, y0_top=True
🎯 ScanoutDMABUF called!  ← Listenerが呼ばれた！
✅ Reply sent from filter
```

✅ **フィルター内で処理すると正常に動作する**

---

## 問題の本質

### 根本原因

**PyGObjectの`Gio.DBusConnection.register_object()`で登録したハンドラーが呼ばれない**

### 確認できたこと

1. ✅ メッセージは正常にP2P接続を通じて到達している
2. ✅ UnixFD転送も正常に機能している
3. ✅ メッセージフィルターでメッセージを検出・処理できる
4. ❌ `register_object()`で登録したメソッドハンドラーが呼ばれない

### 現在の登録コード

```python
introspection_data = Gio.DBusNodeInfo.new_for_xml(self.LISTENER_INTERFACE)
interface_info = introspection_data.interfaces[0]

reg_id1 = self.connection.register_object(
    "/org/qemu/Display1/Listener",
    interface_info,
    self._handle_method_call,    # ← このハンドラーが呼ばれない
    self._handle_get_property,
    None
)
```

### 考えられる原因

1. **PyGObjectのバインディング問題**:
   - Pythonのメソッド（`self._handle_method_call`）をコールバックとして渡す際の問題
   - GLibのCコールバックとPythonメソッドの型変換の問題

2. **register_objectの使い方の問題**:
   - PyGObjectでの正しい使い方が異なる可能性
   - `register_object_with_closures()`を使うべき？

3. **インターフェース定義の問題**:
   - XML定義に何か不備がある可能性

---

## 解決の方向性

### A. 一時的な回避策（現在実装中）

**メッセージフィルター内で全メソッドを処理**

**メリット**:
- すぐに動作する
- UnixFD転送も正常に機能する
- QEMUとの互換性問題なし

**デメリット**:
- 本来のD-Busの使い方ではない
- メッセージフィルターの目的から外れる
- コードが複雑になる

**実装方針**:
```python
def _message_filter(self, connection, message, incoming):
    if incoming and message.get_message_type() == METHOD_CALL:
        member = message.get_member()
        
        if member == "ScanoutDMABUF":
            # フィルター内で処理
            # ...
            return None  # メッセージを消費
        elif member == "UpdateDMABUF":
            # フィルター内で処理
            # ...
            return None
        # 他のメソッドも同様
    
    return message  # その他のメッセージは通常処理
```

### B. 根本的な解決（調査が必要）

**PyGObjectの正しい使い方を調査**

**調査項目**:
1. PyGObjectの公式サンプルコード確認
2. `register_object_with_closures()`の使用
3. 他のPython D-Busライブラリ（pydbus、dbus-python）との比較
4. GLib本家のドキュメント確認

**参考になる可能性のあるコード**:
- qemu-display（Rust、zbus使用）
- PyGObjectの公式テストコード
- GDBusの公式サンプル

---

## 技術的詳細

### P2P接続セットアップ順序

現在の実装:
```
1. socket.socketpair() でUnixドメインソケットペア作成
2. RegisterListener(server_socket) 呼び出し
3. client_socketでP2P接続確立（CLIENT側）
4. GSocketConnectionを作成（UnixFD転送用）
5. Gio.DBusConnection.new_sync() でP2P D-Bus接続
6. connection.add_filter() でメッセージフィルター登録
7. connection.register_object() でインターフェース登録
8. connection.start_message_processing() で処理開始
```

### メッセージフロー

```
QEMU (SERVER)                     Client (CLIENT)
    |                                  |
    | RegisterListener(fd)             |
    |--------------------------------->|
    |                                  | P2P接続確立
    |<---------------------------------|
    |                                  |
    | ScanoutDMABUF(fd, ...)          |
    |--------------------------------->|
    |                                  |
    |                                  | [✅ メッセージフィルター]
    |                                  | [❌ メソッドハンドラー]
    |                                  |
    |<---------------------------------|
    |         Method Reply             |
```

### UnixFD転送の詳細

**QEMU側（送信）**:
```c
// ui/dbus-listener.c:326
qemu_dbus_display1_listener_call_scanout_dmabuf(
    ddl->proxy, 
    g_variant_new_handle(0),  // FDインデックス
    width, height, stride, fourcc, modifier, y0_top,
    G_DBUS_CALL_FLAGS_NONE, -1, 
    fd_list,  // GUnixFDList
    NULL, NULL, NULL
);
```

**Client側（受信）**:
```python
# メッセージフィルター内で
unix_fd_list = message.get_unix_fd_list()
body = message.get_body()
fd_index, width, height, ... = body.unpack()
actual_fd = unix_fd_list.get(fd_index)  # 実際のFDを取得
```

### Fourcc フォーマット

確認されたフォーマット:
- `0x34324258` = "XB24" = XRGB8888（32bit、alpha無視）
- stride = width * 4 (32bit per pixel)

---

## 次のアクション

### 優先度: 高

**方針A: メッセージフィルター内での処理を完成させる**

実装するメソッド:
1. ✅ ScanoutDMABUF（実装済み、動作確認済み）
2. ⬜ UpdateDMABUF
3. ⬜ CursorDefine
4. ⬜ MouseSet
5. ⬜ Scanout (非DMABUF版、念のため)
6. ⬜ Update (非DMABUF版、念のため)

実装ステップ:
1. フィルター内で全メソッドを処理
2. 各メソッドでリプライを送信
3. テストで動作確認
4. WebRTC統合テスト

### 優先度: 中

**方針B: register_objectの問題を調査**

調査ステップ:
1. PyGObjectの公式ドキュメント確認
2. サンプルコード検索
3. 他のライブラリとの比較
4. 可能であれば修正

---

## 関連ファイル

### 実装ファイル

- `/nfs_root/projects2/claude/webrtc_dbus/dbus/p2p_glib.py` (17,025 bytes)
  - P2P D-Bus接続管理
  - メッセージフィルター実装
  - インターフェース登録（問題あり）

- `/nfs_root/projects2/claude/webrtc_dbus/dbus/listener.py` (15,269 bytes)
  - DisplayListener実装
  - ScanoutDMABUF処理

- `/nfs_root/projects2/claude/webrtc_dbus/dbus/register_listener_helper.py`
  - RegisterListener呼び出しヘルパー

### テストスクリプト

- `test_register_listener_v2.py`
  - RegisterListener + SetUIInfo統合テスト
  - 現在使用中

### ログファイル

- `/tmp/qemu_gl_on_stderr.log` - QEMUログ
- `/tmp/client_register_test_v2.log` - クライアントログ
- `/tmp/test_single_interface.log` - Unix.Map削除後のテスト

### QEMU関連

- `/nfs_root/projects2/virtio/qemu/qemu-v9.2.0/ui/dbus-display1.xml`
  - 公式プロトコル定義
- `/nfs_root/projects2/virtio/qemu/qemu-v9.2.0/ui/dbus-listener.c`
  - ScanoutDmabuf送信実装

### 参考実装

- `/nfs_root/projects2/claude/qemu-display/`
  - Rust実装（zbus使用）
  - 正常に動作する参考実装

---

## 結論

### 現状

✅ **メッセージ到達**: ScanoutDMABUFメッセージは正常に届いている  
✅ **UnixFD転送**: ファイルディスクリプタ転送も正常に機能  
✅ **メッセージフィルター**: フィルター内で処理すれば動作する  
❌ **メソッドハンドラー**: `register_object()`で登録したハンドラーが呼ばれない

### 根本原因

**PyGObjectの`register_object()`の使い方に問題がある、またはPyGObjectのバグ**

### 推奨される対応

**短期**: メッセージフィルター内で全メソッドを処理（回避策）  
**中長期**: PyGObjectの正しい使い方を調査、または別のD-Busライブラリへの移行を検討

---

## パフォーマンス測定（Phase 1の結果）

参考: 以前の測定結果

### Version 1（VNC + WebRTC）
- Input Latency: 100-200ms
- Frame Rate: 15-20 FPS

### Version 1.5（D-Bus Input + VNC Display）
- Input Latency: <10ms ✅
- Frame Rate: 15-20 FPS（変化なし）

### Version 2（目標: D-Bus Input + D-Bus Display）
- Input Latency: <10ms（既に達成）
- Frame Rate: 目標 30+ FPS
- 現在: ScanoutDMABUF受信問題を解決中

---

## 環境情報

### QEMU設定

```bash
${QEMU_DIR}/qemu-system-x86_64 \
    -enable-kvm -M q35 -smp 4 -m 4G -cpu host \
    -display dbus,p2p=no,gl=on,addr=unix:path=/tmp/qemu_gl_on_debug.sock \
    -device virtio-vga-gl,hostmem=4G,blob=true,venus=true \
    -device virtio-tablet-pci \
    -device virtio-keyboard-pci \
    -serial file:/tmp/qemu_gl_on_serial.log \
    -netdev user,id=net0,hostfwd=tcp::10022-:22 \
    -device e1000,netdev=net0 \
    -object memory-backend-memfd,id=mem1,size=4G \
    -machine memory-backend=mem1 \
    -drive file=/nfs_root/projects2/virtio/demo/ubuntu-24-04.qcow2
```

### システム情報

- Host: tsubame (192.168.10.101)
- OS: Linux
- QEMU: v9.2.0
- Python: 3.12
- PyGObject: 利用可能（バージョン要確認）
- GLib D-Bus: 使用中

---

## メモ

### 学んだこと

1. **UnixFD転送は問題ない**: Capabilityフラグで確認、実際に動作する
2. **メッセージは届いている**: フィルターで検出できる
3. **PyGObjectの制限**: `register_object()`が期待通りに動作しない
4. **回避策の有効性**: メッセージフィルター内での処理は実用的

### 注意点

1. メッセージフィルター内での処理は本来の用途ではない
2. 全メソッドを手動で処理する必要がある
3. エラーハンドリングに注意が必要
4. 将来的にはPyGObjectの問題を解決すべき

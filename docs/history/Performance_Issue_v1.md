# QEMU D-Bus Display Performance Issue Investigation

**作成日**: 2026-01-20  
**プロジェクト**: /nfs_root/projects2/claude/webrtc_dbus  
**問題**: D-Bus経由の画面キャプチャでフレームが取得できない

---

## 問題の症状

### 現象
- WebRTCサーバーに接続すると画面が黒いまま
- ブラウザでマウス/キーボード操作は正常に動作
- QEMUからScanout/Updateコールバックが全く来ない

### 環境
- QEMU: v9.2.0（カスタムビルド、デバッグログ追加済み）
- 起動オプション: `-display dbus,p2p=no,gl=off -vnc :0`
- VM: Ubuntu 24.04（GDM + Wayland起動中）
- WebRTC実装: aiortc + GLib/Gio (P2P D-Bus接続)

---

## 調査の経緯

### 1. 初期仮説（誤り）
**仮説**: VNCとD-Busの競合が原因  
**検証**: VNCなしでも同じ問題が発生 → **否定**

### 2. QEMUバージョンの影響確認
**検証**: v9.2.0, v9.2.4, v10.2.0で同じ問題  
**結論**: バージョンによる差異なし

### 3. デバッグログ追加による詳細調査
**実施内容**:
- console.c: `dpy_gfx_update()`にデバッグログ追加
- dbus-listener.c: `dbus_gfx_update()`にデバッグログ追加

---

## 判明した事実

### ✅ 正常に動作している部分

1. **RegisterListener**: 成功
   ```
   [LISTENER_NEW] bus_name=:1.1, ddl=0x5d492e596530
   [LISTENER_NEW] dcl.con set to 0x5d492edff8d0 (console_index=0)
   ```

2. **P2P D-Bus接続**: 確立済み
   - GIO socket connection作成: ✅
   - Listener interface登録: ✅
   - Unix.Map interface登録: ✅
   - Message filter登録: ✅

3. **マウス/キーボード入力**: QEMUに正常に届いている
   ```
   Mouse press/release: D-Bus送信 < 3ms
   ```

4. **QEMUの`dpy_gfx_update()`**: 呼ばれている
   ```
   [DPY_UPDATE] Looping listeners for con=0x5d492edff8d0
   [DPY_UPDATE] Checking dcl=0x5d492e596580, dpy_name=dbus
   [DPY_UPDATE]   -> Con matches, checking dpy_gfx_update=0x5b89510eb198
   [DPY_UPDATE]   -> Calling dpy_gfx_update!
   ```

### ❌ 問題がある部分

1. **dbus-listener.cの`dbus_gfx_update()`**: **全く呼ばれていない**
   - `[UPD] dbus_gfx_update`ログが一切出力されない
   - つまり、QEMUは`dpy_gfx_update()`を呼んでいるが、dbus-listener.cの関数には到達していない

---

## 問題の本質

### DisplayChangeListenerの構造

QEMUには複数のDisplayChangeListener (dcl)が存在：

```
1. dcl=0x5d492e596580, dpy_name=dbus       (RegisterListenerで登録？)
2. dcl=0x74b20b646050, dpy_name=vnc        (VNC用)
3. dcl=0x5d492ecf3d10, dpy_name=dbus-console (コンソール用)
```

### 問題の核心

**RegisterListenerで登録したdcl（0x5d492e596530 + 80バイト = 0x5d492e596580）に対して、`dpy_gfx_update()`が呼ばれているが、実装されている`dbus_gfx_update()`には到達していない。**

考えられる原因：
1. `dcl.ops`に設定されているのが`dbus_dcl_ops`ではない可能性
2. `ops->dpy_gfx_update`関数ポインタが別の関数を指している
3. `gl=off`により、別のopsが使われている

### 関連コード（dbus-listener.c）

```c
const DisplayChangeListenerOps dbus_dcl_ops = {
    .dpy_name                = "dbus",
    .dpy_gfx_update          = dbus_gfx_update,  // ← これが呼ばれていない
    .dpy_gfx_switch          = dbus_gfx_switch,
    .dpy_refresh             = dbus_refresh,
    .dpy_mouse_set           = dbus_mouse_set,
    .dpy_cursor_define       = dbus_cursor_define,
};

const DisplayChangeListenerOps dbus_gl_dcl_ops = {
    .dpy_name                = "dbus-gl",
    .dpy_gfx_update          = dbus_gl_gfx_update,  // OpenGL版
    // ...
};

static void dbus_display_listener_constructed(GObject *object) {
    ddl->dcl.ops = &dbus_dcl_ops;
#ifdef CONFIG_OPENGL
    if (display_opengl) {
        ddl->dcl.ops = &dbus_gl_dcl_ops;
    }
#endif
}
```

### 構造体オフセット

```
struct _DBusDisplayListener {
    GObject parent;              // offset 0
    char *bus_name;              // offset ~8
    // ... (約80バイトの他のメンバー)
    DisplayChangeListener dcl;   // offset ~80 ← これが0x5d492e596580
    // ...
};
```

---

## デバッグログの状況

### console.c（QEMU側）

詳細ログは出力されているが、`dpy_name`や`Calling dpy_gfx_update!`が**古いログにしか残っていない**。

最近のログ：
```
[DPY_UPDATE] Checking dcl=0x5d492e596580, dcl->con=0x5d492edff8d0
```

詳細情報（dpy_name等）が出ていない → **リビルドが反映されていない可能性**

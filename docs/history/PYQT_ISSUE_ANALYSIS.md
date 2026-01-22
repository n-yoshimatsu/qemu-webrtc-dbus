# PyQt5 QOffscreenSurface 問題分析

## 現象

### 実行結果
```
Step 5: Call surface.create()
Segmentation fault (core dumped)
```

### エラーメッセージ
```
QObject::connect: Cannot connect (nullptr)::destroyed(QObject*) to QOffscreenSurface::screenDestroyed(QObject*)
```

## 根本原因

1. **Screen オブジェクトが nullptr**
   - Qt が画面（QScreen）を取得できない
   - headless環境で画面情報がない

2. **QOffscreenSurface.create() で segfault**
   - screen が nullptr の状態で内部的にアクセス
   - C++ レイヤーで nullptr dereference

3. **プラットフォームプラグインの問題**
   - `QT_QPA_PLATFORM=offscreen`: 専用プラグインだが実装に問題
   - `QT_QPA_PLATFORM=minimal`: 最小限だが同じ問題
   - `QT_QPA_PLATFORM=eglfs`: 画面が必要

## システム環境

- GPU: 利用可能 (`/dev/dri/card1`, `/dev/dri/renderD128`)
- libEGL: 利用可能 (`libEGL.so.1`)
- libGBM: 利用可能 (`libgbm.so.1`)
- DMA-BUF EGL 拡張: すべて動作確認済み ✓

## 結論

**PyQt5 の QOffscreenSurface は headless 環境での使用を想定していない**

理由：
- QOffscreenSurface は QScreen に依存
- Minimal/Offscreen プラットフォームプラグインが QScreen を提供できない
- QScreen なしで surface.create() は segfault

## 代替案の必要性

PyQt5 での EGL/OpenGL コンテキスト作成は、QOffscreenSurface を経由せず以下の方法で実装する必要がある：

1. **直接 EGL + GBM**: libEGL.so.1 と libgbm.so.1 を直接使用
2. **Qt を使わない**: EGL コンテキストを手動作成、PyOpenGL だけで十分

この場合、PyQt5 の価値は失われる（EGL 抽象化が機能しないため）。

#!/bin/bash
#
# QEMU起動（gl=on + デバッグログ + SSH対応）
#

# パス設定
WDIR="/nfs_root/projects2/virtio"
QEMU_DIR="${WDIR}/qemu/qemu-v9.2.0/build"
IMG_DIR="${WDIR}/demo"
IMG="${IMG_DIR}/ubuntu-24-04.qcow2"
SOCKET_PATH="/tmp/qemu_dbus.sock"
QEMU_LOG="/tmp/qemu_gl_on_stdout.log"
QEMU_ERR="/tmp/qemu_gl_on_stderr.log"
SERIAL_LOG="/tmp/qemu_gl_on_serial.log"

echo "================================================================"
echo "QEMU起動（gl=on + デバッグログ）"
echo "================================================================"
echo ""

# 既存のQEMUプロセスを停止
echo "既存のQEMUプロセスを停止..."
pkill -9 qemu-system 2>/dev/null
sleep 2

# 既存のD-Busデーモンを終了
echo "既存のD-Busデーモンを終了..."
pkill -f "dbus-daemon.*${SOCKET_PATH}" 2>/dev/null
sleep 1
rm -f ${SOCKET_PATH}

# ログファイルをクリア
rm -f ${QEMU_LOG} ${QEMU_ERR} ${SERIAL_LOG}

# D-Busデーモンを起動
echo "D-Busデーモンを起動..."
dbus-daemon --session --fork \
     --print-address=1 \
     --print-pid=1 \
     --address=unix:path=${SOCKET_PATH}

chmod 777 ${SOCKET_PATH}
export DBUS_SESSION_BUS_ADDRESS=unix:path=${SOCKET_PATH}

echo "✓ D-Busデーモン起動完了"
echo ""
echo "QEMU設定:"
echo "  D-Bus Display: unix:path=${SOCKET_PATH}"
echo "  OpenGL: ON"
echo "  VMイメージ: ${IMG}"
echo "  ログ:"
echo "    stdout: ${QEMU_LOG}"
echo "    stderr: ${QEMU_ERR}"
echo "    serial: ${SERIAL_LOG}"
echo ""

# QEMU起動（バックグラウンド、ログファイル出力）
${QEMU_DIR}/qemu-system-x86_64 \
    -enable-kvm \
    -M q35 \
    -smp 4 \
    -m 4G \
    -cpu host \
    -display dbus,p2p=no,gl=on,addr=unix:path=${SOCKET_PATH} \
    -device virtio-vga-gl,hostmem=4G,blob=true,venus=true \
    -device virtio-tablet-pci \
    -device virtio-keyboard-pci \
    -serial file:${SERIAL_LOG} \
    -netdev user,id=net0,hostfwd=tcp::10022-:22 \
    -device e1000,netdev=net0 \
    -object memory-backend-memfd,id=mem1,size=4G \
    -machine memory-backend=mem1 \
    -drive file=${IMG} \
    > ${QEMU_LOG} 2> ${QEMU_ERR} &

QEMU_PID=$!

sleep 3

# QEMUが起動したか確認
if ps -p ${QEMU_PID} > /dev/null; then
    echo "✓ QEMU起動成功"
    echo "  PID: ${QEMU_PID}"
    echo ""
    echo "ログ確認方法:"
    echo "  tail -f ${QEMU_LOG}"
    echo "  tail -f ${QEMU_ERR}"
    echo ""
    echo "WebRTCサーバー起動方法:"
    echo "  export DBUS_SESSION_BUS_ADDRESS=unix:path=${SOCKET_PATH}"
    echo "  python3 server/main.py"
else
    echo "✗ QEMU起動失敗"
    echo ""
    echo "エラーログ:"
    cat ${QEMU_ERR}
    exit 1
fi

#!/bin/bash
#
# QEMU起動（gl=on + デバッグログ + SSH対応）
#

# パス設定

WDIR="/home/ubuntu/work/qemu/"
VM_NAME="ubuntu-desktop"
QEMU_DIR=${WDIR}/qemu-v9.2.0/build
IMG_DIR="${WDIR}/demo"
IMG="${IMG_DIR}/noble-server-cloudimg-arm64.img"
SEED="${IMG_DIR}/seed.iso"

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


# UEFI環境セットアップ
NVRAM_DIR="/var/lib/qemu/nvram"
VARS_FILE="${NVRAM_DIR}/${VM_NAME}-vars-pflash.raw"

# UEFI環境確認・作成
if [ ! -f /usr/share/AAVMF/AAVMF_CODE.fd ]; then
    echo "Error: AAVMF not found. Installing..."
    sudo apt install -y qemu-efi-aarch64
fi

mkdir -p "$NVRAM_DIR"
if [ ! -f "$VARS_FILE" ]; then
    echo "Creating UEFI vars for $VM_NAME"
    cp /usr/share/AAVMF/AAVMF_VARS.fd "$VARS_FILE"
fi

# 環境変数設定
export MESA_GL_VERSION_OVERRIDE=4.6
export MESA_GLSL_VERSION_OVERRIDE=460
export LIBGL_ALWAYS_SOFTWARE=0
export GALLIUM_DRIVER=virpipe

# 追加の環境設定
export MESA_LOADER_DRIVER_OVERRIDE=nouveau
export EGL_PLATFORM=drm
export GBM_BACKEND=nvidia-drm
export __EGL_VENDOR_LIBRARY_DIRS=/usr/share/glvnd/egl_vendor.d
export LIBGL_DRIVERS_PATH=/usr/lib/x86_64-linux-gnu/dri

export __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json
#    -device virtio-vga-gl,hostmem=8G,blob=true,venus=true,xres=1280,yres=720 \

# QEMU起動（バックグラウンド、ログファイル出力）
${QEMU_DIR}/qemu-system-aarch64 \
    -enable-kvm \
    -machine virt,accel=kvm,acpi=on,gic-version=host \
    -cpu host \
    -m 8G \
    -smp 8,cores=4,threads=2 \
    -display dbus,p2p=no,gl=on,addr=unix:path=${SOCKET_PATH},rendernode=/dev/dri/renderD128 \
    -device virtio-gpu-gl-pci,xres=1280,yres=720,hostmem=8G,blob=true,venus=true \
    -device virtio-tablet-pci \
    -device virtio-keyboard-pci \
    -serial file:${SERIAL_LOG} \
    -netdev user,id=net0,hostfwd=tcp::10022-:22 \
    -device e1000,netdev=net0 \
    -object memory-backend-memfd,id=mem1,size=8G \
    -machine memory-backend=mem1 \
    -drive if=pflash,format=raw,readonly=on,file=/usr/share/AAVMF/AAVMF_CODE.fd \
    -drive if=pflash,format=raw,file="$VARS_FILE" \
    -drive if=none,file=${IMG},format=qcow2,id=hd0 \
    -device virtio-blk-pci,drive=hd0,bootindex=0 \
    -drive if=none,file=${SEED},format=raw,readonly=on,id=seed0 \
    -device virtio-blk-pci,drive=seed0,bootindex=1 \
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

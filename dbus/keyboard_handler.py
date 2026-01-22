"""D-Bus keyboard input handler"""
import logging
from .keymap import js_code_to_qemu

logger = logging.getLogger(__name__)

class KeyboardHandler:
    def __init__(self, bus, console_path):
        self.bus = bus
        self.console_path = console_path
        
    def handle_key_event(self, js_code, is_press):
        """Handle keyboard event from browser
        
        Args:
            js_code: JavaScript KeyboardEvent.code (e.g., "KeyA")
            is_press: True for keydown, False for keyup
        """
        try:
            qemu_code = js_code_to_qemu(js_code)
            if qemu_code is None:
                logger.warning(f"Unknown key: {js_code}")
                return
            
            logger.debug(f"Keyboard: {js_code} -> {qemu_code}, press={is_press}")
                
            kbd_proxy = self.bus.get_proxy(
                "org.qemu",
                self.console_path,
                "org.qemu.Display1.Keyboard"
            )
            
            if is_press:
                kbd_proxy.Press(qemu_code)
            else:
                kbd_proxy.Release(qemu_code)
                
        except Exception as e:
            logger.error(f"Keyboard error: {e}")

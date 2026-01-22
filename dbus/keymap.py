"""
JavaScript KeyboardEvent.code to QEMU keycode mapping

QEMU uses "xtkbd + special re-encoding of high bit" format
Reference: https://github.com/qemu/keycodemapdb
"""

# JavaScript KeyboardEvent.code → QEMU keycode
# Format: QEMU keycode (decimal)
JS_TO_QEMU = {
    # Writing system keys
    'Backquote': 41,
    'Backslash': 43,
    'Backspace': 14,
    'BracketLeft': 26,
    'BracketRight': 27,
    'Comma': 51,
    'Digit0': 11,
    'Digit1': 2,
    'Digit2': 3,
    'Digit3': 4,
    'Digit4': 5,
    'Digit5': 6,
    'Digit6': 7,
    'Digit7': 8,
    'Digit8': 9,
    'Digit9': 10,
    'Equal': 13,
    'IntlBackslash': 86,
    'IntlRo': 89,
    'IntlYen': 124,
    'KeyA': 30,
    'KeyB': 48,
    'KeyC': 46,
    'KeyD': 32,
    'KeyE': 18,
    'KeyF': 33,
    'KeyG': 34,
    'KeyH': 35,
    'KeyI': 23,
    'KeyJ': 36,
    'KeyK': 37,
    'KeyL': 38,
    'KeyM': 50,
    'KeyN': 49,
    'KeyO': 24,
    'KeyP': 25,
    'KeyQ': 16,
    'KeyR': 19,
    'KeyS': 31,
    'KeyT': 20,
    'KeyU': 22,
    'KeyV': 47,
    'KeyW': 17,
    'KeyX': 45,
    'KeyY': 21,
    'KeyZ': 44,
    'Minus': 12,
    'Period': 52,
    'Quote': 40,
    'Semicolon': 39,
    'Slash': 53,
    
    # Functional keys
    'AltLeft': 56,
    'AltRight': 184,  # 0xb8 (56 | 0x80)
    'CapsLock': 58,
    'ControlLeft': 29,
    'ControlRight': 157,  # 0x9d (29 | 0x80)
    'Enter': 28,
    'MetaLeft': 219,  # 0xdb (Windows/Super key)
    'MetaRight': 220,  # 0xdc
    'ShiftLeft': 42,
    'ShiftRight': 54,
    'Space': 57,
    'Tab': 15,
    
    # Control pad section
    'Delete': 211,  # 0xd3
    'End': 207,  # 0xcf
    'Home': 199,  # 0xc7
    'Insert': 210,  # 0xd2
    'PageDown': 209,  # 0xd1
    'PageUp': 201,  # 0xc9
    
    # Arrow pad
    'ArrowDown': 208,  # 0xd0
    'ArrowLeft': 203,  # 0xcb
    'ArrowRight': 205,  # 0xcd
    'ArrowUp': 200,  # 0xc8
    
    # Numpad section
    'NumLock': 69,
    'Numpad0': 82,
    'Numpad1': 79,
    'Numpad2': 80,
    'Numpad3': 81,
    'Numpad4': 75,
    'Numpad5': 76,
    'Numpad6': 77,
    'Numpad7': 71,
    'Numpad8': 72,
    'Numpad9': 73,
    'NumpadAdd': 78,
    'NumpadDecimal': 83,
    'NumpadDivide': 181,  # 0xb5
    'NumpadEnter': 156,  # 0x9c
    'NumpadMultiply': 55,
    'NumpadSubtract': 74,
    
    # Function section
    'Escape': 1,
    'F1': 59,
    'F2': 60,
    'F3': 61,
    'F4': 62,
    'F5': 63,
    'F6': 64,
    'F7': 65,
    'F8': 66,
    'F9': 67,
    'F10': 68,
    'F11': 87,
    'F12': 88,
    'PrintScreen': 183,  # 0xb7
    'ScrollLock': 70,
    'Pause': 119,  # 0x77
}


def js_code_to_qemu(js_code: str) -> int:
    """
    Convert JavaScript KeyboardEvent.code to QEMU keycode
    
    Args:
        js_code: JavaScript code (e.g., "KeyA", "Enter")
        
    Returns:
        QEMU keycode (integer), or None if unknown
    """
    return JS_TO_QEMU.get(js_code)


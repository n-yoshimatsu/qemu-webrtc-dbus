// Keyboard event handling for WebRTC client
// Document-level capture for reliability

function setupKeyboardHandling(dataChannel) {
    console.log('[Keyboard] Setting up document-level keyboard handling');
    console.log('[Keyboard] DataChannel state:', dataChannel.readyState);
    
    let isEnabled = false;
    
    // Enable keyboard when video is clicked
    const videoElement = document.getElementById('qemu-screen');
    if (videoElement) {
        videoElement.addEventListener('click', () => {
            isEnabled = true;
            console.log('[Keyboard] ✅ Keyboard input ENABLED (video clicked)');
        });
        console.log('[Keyboard] Video element found, click to enable keyboard');
    } else {
        console.error('[Keyboard] ✗ Video element not found!');
        // Enable anyway for testing
        isEnabled = true;
    }
    
    // Document-level keydown handler
    document.addEventListener('keydown', (event) => {
        if (!isEnabled) {
            return; // Keyboard not enabled yet
        }
        
        console.log('[Keyboard] KEYDOWN:', event.code, '| DataChannel:', dataChannel.readyState);
        
        // Prevent default browser behavior
        event.preventDefault();
        event.stopPropagation();
        
        if (dataChannel.readyState === 'open') {
            const message = {
                type: 'keyboard',
                code: event.code,
                action: 'press'
            };
            
            try {
                dataChannel.send(JSON.stringify(message));
                console.log('[Keyboard] ✓✓✓ Key press SENT:', event.code);
            } catch (error) {
                console.error('[Keyboard] ✗ Send error:', error);
            }
        } else {
            console.warn('[Keyboard] ✗ DataChannel not open:', dataChannel.readyState);
        }
    }, true); // Use capture phase
    
    // Document-level keyup handler
    document.addEventListener('keyup', (event) => {
        if (!isEnabled) {
            return;
        }
        
        console.log('[Keyboard] KEYUP:', event.code);
        event.preventDefault();
        event.stopPropagation();
        
        if (dataChannel.readyState === 'open') {
            const message = {
                type: 'keyboard',
                code: event.code,
                action: 'release'
            };
            
            try {
                dataChannel.send(JSON.stringify(message));
                console.log('[Keyboard] ✓ Key release sent:', event.code);
            } catch (error) {
                console.error('[Keyboard] ✗ Send error:', error);
            }
        }
    }, true); // Use capture phase
    
    console.log('[Keyboard] ✅✅✅ Document-level keyboard handlers installed');
    console.log('[Keyboard] Click the video to enable, then press any key');
}

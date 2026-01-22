"""
EGL-based OpenGL DMA-BUF Renderer

Uses direct EGL calls for headless rendering of DMA-BUF.
Dynamic function loading for EGL extensions.
"""

import logging
import numpy as np
from OpenGL import GL
import os
import ctypes
from ctypes import c_int, c_void_p, c_uint, POINTER, c_int32

logger = logging.getLogger(__name__)

# EGL constants
EGL_NO_DISPLAY = c_void_p(0)
EGL_NO_CONTEXT = c_void_p(0)
EGL_NO_SURFACE = c_void_p(0)
EGL_NO_IMAGE_KHR = c_void_p(0)
EGL_NONE = 0x3038
EGL_DEFAULT_DISPLAY = c_void_p(0)
EGL_EXTENSIONS = 0x3055
EGL_OPENGL_API = 0x30A2
EGL_OPENGL_BIT = 0x0008
EGL_RENDERABLE_TYPE = 0x3040
EGL_SURFACE_TYPE = 0x3033
EGL_PBUFFER_BIT = 0x0001
EGL_DEPTH_SIZE = 0x3025

EGL_WIDTH = 0x3057
EGL_HEIGHT = 0x3056
EGL_LINUX_DRM_FOURCC_EXT = 0x3271
EGL_DMA_BUF_PLANE0_FD_EXT = 0x3272
EGL_DMA_BUF_PLANE0_OFFSET_EXT = 0x3273
EGL_DMA_BUF_PLANE0_PITCH_EXT = 0x3274
EGL_DMA_BUF_PLANE0_MODIFIER_LO_EXT = 0x3443
EGL_DMA_BUF_PLANE0_MODIFIER_HI_EXT = 0x3444
EGL_LINUX_DMA_BUF_EXT = 0x3270

# OpenGL constants
GL_TEXTURE_2D = 0x0DE1
GL_RGBA = 0x1908
GL_UNSIGNED_BYTE = 0x1401
GL_COLOR_ATTACHMENT0 = 0x8CE0
GL_FRAMEBUFFER = 0x8D40
GL_FRAMEBUFFER_COMPLETE = 0x8CD5

# Load EGL library
try:
    egl_lib = ctypes.CDLL('libEGL.so.1')
except OSError:
    try:
        egl_lib = ctypes.CDLL('libEGL.so')
    except OSError:
        logger.error("Failed to load EGL library")
        egl_lib = None

# EGL base functions with proper signatures
if egl_lib:
    eglGetDisplay = egl_lib.eglGetDisplay
    eglGetDisplay.argtypes = [c_void_p]
    eglGetDisplay.restype = c_void_p
    
    eglInitialize = egl_lib.eglInitialize
    eglInitialize.argtypes = [c_void_p, POINTER(c_int), POINTER(c_int)]
    eglInitialize.restype = c_int
    
    eglChooseConfig = egl_lib.eglChooseConfig
    eglChooseConfig.argtypes = [c_void_p, POINTER(c_int), c_void_p, c_int, POINTER(c_int)]
    eglChooseConfig.restype = c_int
    
    eglCreateContext = egl_lib.eglCreateContext
    eglCreateContext.argtypes = [c_void_p, c_void_p, c_void_p, POINTER(c_int)]
    eglCreateContext.restype = c_void_p
    
    eglMakeCurrent = egl_lib.eglMakeCurrent
    eglMakeCurrent.argtypes = [c_void_p, c_void_p, c_void_p, c_void_p]
    eglMakeCurrent.restype = c_int
    
    eglDestroyContext = egl_lib.eglDestroyContext
    eglDestroyContext.argtypes = [c_void_p, c_void_p]
    eglDestroyContext.restype = c_int
    
    eglTerminate = egl_lib.eglTerminate
    eglTerminate.argtypes = [c_void_p]
    eglTerminate.restype = c_int
    
    eglGetProcAddress = egl_lib.eglGetProcAddress
    eglGetProcAddress.argtypes = [ctypes.c_char_p]
    eglGetProcAddress.restype = c_void_p
    
    eglGetCurrentDisplay = egl_lib.eglGetCurrentDisplay
    eglGetCurrentDisplay.restype = c_void_p

    eglGetError = egl_lib.eglGetError
    eglGetError.restype = c_int

    eglQueryString = egl_lib.eglQueryString
    eglQueryString.argtypes = [c_void_p, c_int]
    eglQueryString.restype = c_void_p

    eglBindAPI = egl_lib.eglBindAPI
    eglBindAPI.argtypes = [c_uint]
    eglBindAPI.restype = c_int

    eglCreatePbufferSurface = egl_lib.eglCreatePbufferSurface
    eglCreatePbufferSurface.argtypes = [c_void_p, c_void_p, POINTER(c_int)]
    eglCreatePbufferSurface.restype = c_void_p

    eglDestroySurface = egl_lib.eglDestroySurface
    eglDestroySurface.argtypes = [c_void_p, c_void_p]
    eglDestroySurface.restype = c_int
    
    # Dynamic extension function loading
    def _load_egl_extension(func_name, argtypes, restype=c_void_p):
        """Load EGL extension function dynamically."""
        if isinstance(func_name, str):
            func_name = func_name.encode()
        addr = eglGetProcAddress(func_name)
        if addr:
            func = ctypes.CFUNCTYPE(restype, *argtypes)(addr)
            logger.info(f"✓ {func_name.decode()} loaded")
            return func
        else:
            logger.warning(f"Could not load EGL extension: {func_name}")
            return None
    
    # Load DMA-BUF extension functions
    eglCreateImageKHR = None
    eglDestroyImageKHR = None
    glEGLImageTargetTexture2DOES = None
    
    try:
        # eglCreateImageKHR
        eglCreateImageKHR = _load_egl_extension(
            b'eglCreateImageKHR',
            [c_void_p, c_void_p, c_uint, c_void_p, POINTER(c_int)],
            c_void_p
        )
        
        # eglDestroyImageKHR
        eglDestroyImageKHR = _load_egl_extension(
            b'eglDestroyImageKHR',
            [c_void_p, c_void_p],
            c_int
        )
        
        # glEGLImageTargetTexture2DOES
        glEGLImageTargetTexture2DOES = _load_egl_extension(
            b'glEGLImageTargetTexture2DOES',
            [c_uint, c_void_p],
            None
        )
        
    except Exception as e:
        logger.warning(f"Error loading EGL extensions: {e}")
else:
    logger.error("EGL library not available - DMA-BUF rendering will not work")


class EGLDMABUFRenderer:
    """
    Direct EGL-based DMA-BUF renderer for headless environments.
    """

    def __init__(self):
        self.display = None
        self.context = None
        self.config = None
        self.surface = None
        self.initialized = False
        self.egl_extensions = ""

    def initialize(self):
        """Initialize EGL display and OpenGL context for headless rendering."""
        try:
            logger.info("Initializing direct EGL OpenGL renderer...")

            if not egl_lib:
                raise RuntimeError("EGL library not available")

            # Prefer surfaceless EGL in headless environments
            if "EGL_PLATFORM" not in os.environ:
                os.environ["EGL_PLATFORM"] = "surfaceless"

            # Get EGL display (retry once if initialization fails)
            self.display = eglGetDisplay(EGL_DEFAULT_DISPLAY)
            if not self.display:
                raise RuntimeError("Failed to get EGL display")

            # Initialize EGL
            major = c_int()
            minor = c_int()
            if not eglInitialize(self.display, ctypes.byref(major), ctypes.byref(minor)):
                err = eglGetError()
                raise RuntimeError(f"Failed to initialize EGL (err=0x{err:04x})")

            logger.info(f"✓ EGL initialized: version {major.value}.{minor.value}")

            # Bind OpenGL API (not OpenGL ES)
            if not eglBindAPI(EGL_OPENGL_API):
                raise RuntimeError("Failed to bind EGL_OPENGL_API")

            # Choose EGL config
            config_attribs = [
                0x3024, 8,  # EGL_RED_SIZE
                0x3023, 8,  # EGL_GREEN_SIZE
                0x3022, 8,  # EGL_BLUE_SIZE
                0x3021, 8,  # EGL_ALPHA_SIZE
                EGL_DEPTH_SIZE, 4,
                EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
                EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
                EGL_NONE
            ]
            
            configs = (c_void_p * 1)()
            num_configs = c_int()
            
            if not eglChooseConfig(self.display, 
                                 (c_int * len(config_attribs))(*config_attribs),
                                 configs, 1, ctypes.byref(num_configs)):
                raise RuntimeError("Failed to choose EGL config")
            
            if num_configs.value == 0:
                raise RuntimeError("No suitable EGL config found")
            
            self.config = configs[0]
            logger.info("✓ EGL config selected")

            # Create EGL context (default version for bound API)
            context_attribs = [EGL_NONE]

            self.context = eglCreateContext(self.display, self.config, 
                                          EGL_NO_CONTEXT,
                                          (c_int * len(context_attribs))(*context_attribs))
            if not self.context:
                raise RuntimeError("Failed to create EGL context")

            logger.info("✓ EGL context created")

            # Query extensions for surfaceless support and DMA-BUF import
            ext_ptr = eglQueryString(self.display, EGL_EXTENSIONS)
            if ext_ptr:
                self.egl_extensions = ctypes.cast(ext_ptr, ctypes.c_char_p).value.decode()
            else:
                self.egl_extensions = ""

            # Make context current (surfaceless if supported, otherwise PBuffer)
            if "EGL_KHR_surfaceless_context" in self.egl_extensions:
                if not eglMakeCurrent(self.display, EGL_NO_SURFACE, EGL_NO_SURFACE, self.context):
                    raise RuntimeError("Failed to make EGL context current (surfaceless)")
                logger.info("✓ EGL context made current (surfaceless)")
            else:
                pbuffer_attribs = [
                    EGL_WIDTH, 1,
                    EGL_HEIGHT, 1,
                    EGL_NONE
                ]
                self.surface = eglCreatePbufferSurface(
                    self.display,
                    self.config,
                    (c_int * len(pbuffer_attribs))(*pbuffer_attribs)
                )
                if not self.surface:
                    raise RuntimeError("Failed to create PBuffer surface")
                if not eglMakeCurrent(self.display, self.surface, self.surface, self.context):
                    raise RuntimeError("Failed to make EGL context current (PBuffer)")
                logger.info("✓ EGL context made current (PBuffer)")

            self.initialized = True
            return True

        except Exception as e:
            logger.error(f"EGL initialization failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def render_from_dmabuf(self, dmabuf_fd, width, height, stride, fourcc, modifier):
        """
        Render DMA-BUF to RGB using direct EGL OpenGL with extensions.

        Args:
            dmabuf_fd: DMA-BUF file descriptor
            width, height: Dimensions
            stride: Bytes per row
            fourcc: Pixel format
            modifier: DMA-BUF modifier

        Returns:
            RGB NumPy array or None
        """
        if not self.initialized:
            logger.error("Renderer not initialized")
            return None

        if not eglCreateImageKHR or not glEGLImageTargetTexture2DOES:
            logger.error("EGL DMA-BUF extensions not available")
            return None

        try:
            # Context is already current from initialization
            # Use the stored EGL display
            egl_display = self.display
            if not egl_display:
                logger.error("No EGL display available")
                return None

            # Validate required extensions for DMA-BUF import
            if "EGL_EXT_image_dma_buf_import" not in self.egl_extensions:
                logger.error("EGL_EXT_image_dma_buf_import not supported")
                return None
            if modifier != 0 and "EGL_EXT_image_dma_buf_import_modifiers" not in self.egl_extensions:
                logger.error("EGL_EXT_image_dma_buf_import_modifiers not supported")
                return None

            # Create EGL image from DMA-BUF
            # Build attribute list
            attrs = (c_int * 20)()
            attr_idx = 0
            
            attrs[attr_idx] = EGL_WIDTH
            attr_idx += 1
            attrs[attr_idx] = width
            attr_idx += 1
            
            attrs[attr_idx] = EGL_HEIGHT
            attr_idx += 1
            attrs[attr_idx] = height
            attr_idx += 1
            
            attrs[attr_idx] = EGL_LINUX_DRM_FOURCC_EXT
            attr_idx += 1
            attrs[attr_idx] = fourcc
            attr_idx += 1
            
            attrs[attr_idx] = EGL_DMA_BUF_PLANE0_FD_EXT
            attr_idx += 1
            attrs[attr_idx] = dmabuf_fd
            attr_idx += 1
            
            attrs[attr_idx] = EGL_DMA_BUF_PLANE0_OFFSET_EXT
            attr_idx += 1
            attrs[attr_idx] = 0
            attr_idx += 1
            
            attrs[attr_idx] = EGL_DMA_BUF_PLANE0_PITCH_EXT
            attr_idx += 1
            attrs[attr_idx] = stride
            attr_idx += 1
            
            # Add modifier if not 0
            if modifier != 0:
                attrs[attr_idx] = EGL_DMA_BUF_PLANE0_MODIFIER_LO_EXT
                attr_idx += 1
                attrs[attr_idx] = modifier & 0xFFFFFFFF
                attr_idx += 1
                
                attrs[attr_idx] = EGL_DMA_BUF_PLANE0_MODIFIER_HI_EXT
                attr_idx += 1
                attrs[attr_idx] = (modifier >> 32) & 0xFFFFFFFF
                attr_idx += 1
            
            attrs[attr_idx] = EGL_NONE
            
            # Call eglCreateImageKHR
            egl_image = eglCreateImageKHR(c_void_p(egl_display), EGL_NO_CONTEXT,
                                         EGL_LINUX_DMA_BUF_EXT, None, attrs)

            if not egl_image:
                logger.error("Failed to create EGL image from DMA-BUF")
                return None

            logger.info(f"✓ EGL image created from DMA-BUF: fd={dmabuf_fd}, size={width}x{height}")

            # Create OpenGL texture from EGL image
            texture_id = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, texture_id)
            
            # Call glEGLImageTargetTexture2DOES
            glEGLImageTargetTexture2DOES(GL.GL_TEXTURE_2D, egl_image)

            logger.info(f"✓ OpenGL texture created from EGL image: texture_id={texture_id}")

            # Create FBO for rendering
            fbo_id = GL.glGenFramebuffers(1)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo_id)
            GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                                     GL.GL_TEXTURE_2D, texture_id, 0)

            if GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) != GL.GL_FRAMEBUFFER_COMPLETE:
                logger.error("FBO not complete")
                GL.glDeleteFramebuffers(1, [fbo_id])
                GL.glDeleteTextures(1, [texture_id])
                eglDestroyImageKHR(c_void_p(egl_display), egl_image)
                return None

            # Read pixels from FBO
            GL.glReadBuffer(GL.GL_COLOR_ATTACHMENT0)
            rgb_data = GL.glReadPixels(0, 0, width, height, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)

            # Convert to NumPy array
            rgb_array = np.frombuffer(rgb_data, dtype=np.uint8).reshape(height, width, 3)

            # Cleanup
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
            GL.glDeleteFramebuffers(1, [fbo_id])
            GL.glDeleteTextures(1, [texture_id])
            eglDestroyImageKHR(c_void_p(egl_display), egl_image)

            logger.info(f"✓ Rendered DMA-BUF to RGB: {rgb_array.shape}")
            return rgb_array

        except Exception as e:
            logger.error(f"DMA-BUF rendering failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def cleanup(self):
        """Cleanup EGL resources."""
        try:
            if self.context and self.display:
                if self.surface:
                    eglMakeCurrent(self.display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT)
                    eglDestroySurface(self.display, self.surface)
                    self.surface = None
                else:
                    eglMakeCurrent(self.display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT)
                eglDestroyContext(self.display, self.context)
                self.context = None
            
            if self.display:
                eglTerminate(self.display)
                self.display = None
            
            self.initialized = False
            logger.info("EGL renderer cleaned up")
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")


# Global renderer instance
_renderer = None

def get_renderer():
    """Get or create global renderer instance."""
    global _renderer
    if _renderer is None:
        _renderer = EGLDMABUFRenderer()
    return _renderer

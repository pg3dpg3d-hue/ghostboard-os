"""Small X11 helpers. No camera imports, subprocess shell or network access."""
import ctypes as C
import ctypes.util
import os


class Desktop:
    """Client-scoped cursor visibility and keyboard authorization through Xlib."""

    def __init__(self, display=None):
        self.x = C.CDLL(ctypes.util.find_library('X11') or 'libX11.so.6')
        self.f = C.CDLL(ctypes.util.find_library('Xfixes') or 'libXfixes.so.3')
        self.x.XOpenDisplay.argtypes = [C.c_char_p]
        self.x.XOpenDisplay.restype = C.c_void_p
        self.x.XDefaultRootWindow.argtypes = [C.c_void_p]
        self.x.XDefaultRootWindow.restype = C.c_ulong
        self.x.XQueryKeymap.argtypes = [C.c_void_p, C.POINTER(C.c_char)]
        self.x.XKeysymToKeycode.argtypes = [C.c_void_p, C.c_ulong]
        self.x.XKeysymToKeycode.restype = C.c_ubyte
        self.x.XFlush.argtypes = [C.c_void_p]
        self.x.XCloseDisplay.argtypes = [C.c_void_p]
        for name in ('XFixesHideCursor', 'XFixesShowCursor'):
            getattr(self.f, name).argtypes = [C.c_void_p, C.c_ulong]
        self.display = self.x.XOpenDisplay((display or os.environ.get('DISPLAY', ':0')).encode())
        if not self.display:
            raise RuntimeError('Cannot open the local X11 display.')
        self.root = self.x.XDefaultRootWindow(self.display)
        self.hidden = False
        self.keycode = self.x.XKeysymToKeycode(self.display, 0xffc5)  # F8

    def authorized(self):
        keys = C.create_string_buffer(32)
        self.x.XQueryKeymap(self.display, keys)
        return bool(self.keycode and keys.raw[self.keycode // 8] & (1 << (self.keycode % 8)))

    def visible(self, visible):
        if self.hidden == (not visible):
            return
        fn = self.f.XFixesShowCursor if visible else self.f.XFixesHideCursor
        fn(self.display, self.root)
        self.x.XFlush(self.display)
        self.hidden = not visible

    def close(self):
        if self.display:
            self.visible(True)
            self.x.XCloseDisplay(self.display)
            self.display = None

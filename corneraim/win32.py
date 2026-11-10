import ctypes
import sys
from ctypes import wintypes

PER_MONITOR_AWARE_V2 = -4
WM_GETMINMAXINFO = 0x0024
WM_NCHITTEST = 0x0084
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
ULW_ALPHA = 0x00000002
ULW_EX_NORESIZE = 0x00000008
HTCLIENT = 1
HTCAPTION = 2
RESIZE_HITS = {
    (-1, 0): 10, (1, 0): 11, (0, -1): 12, (-1, -1): 13,
    (1, -1): 14, (0, 1): 15, (-1, 1): 16, (1, 1): 17,
}


class _BitmapInfo(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD), ("width", wintypes.LONG), ("height", wintypes.LONG),
        ("planes", wintypes.WORD), ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
        ("image_size", wintypes.DWORD), ("x_density", wintypes.LONG),
        ("y_density", wintypes.LONG), ("colors", wintypes.DWORD), ("important", wintypes.DWORD),
    ]


class _Blend(ctypes.Structure):
    _fields_ = [(name, wintypes.BYTE) for name in ("op", "flags", "opacity", "format")]


class _LayerUpdate(ctypes.Structure):
    _fields_ = [
        ("struct_size", wintypes.DWORD), ("destination_dc", wintypes.HDC),
        ("destination", ctypes.POINTER(wintypes.POINT)), ("extent", ctypes.POINTER(wintypes.SIZE)),
        ("source_dc", wintypes.HDC), ("origin", ctypes.POINTER(wintypes.POINT)),
        ("color_key", wintypes.DWORD), ("blend", ctypes.POINTER(_Blend)),
        ("flags", wintypes.DWORD), ("dirty", ctypes.POINTER(wintypes.RECT)),
    ]


class _Monitor(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD), ("bounds", wintypes.RECT), ("work", wintypes.RECT),
        ("flags", wintypes.DWORD),
    ]


class _MinMax(ctypes.Structure):
    _fields_ = [(name, wintypes.POINT) for name in
                ("reserved", "max_size", "max_position", "min_track", "max_track")]


if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    _comctl32 = ctypes.WinDLL("comctl32", use_last_error=True)

    def _api(library, name, result, *args):
        function = getattr(library, name)
        function.argtypes = args
        function.restype = result
        return function

    _handle, _bool, _ptr = wintypes.HANDLE, wintypes.BOOL, ctypes.c_void_p
    _int, _uint, _size_t = ctypes.c_int, wintypes.UINT, ctypes.c_size_t
    _long_ptr = ctypes.c_ssize_t
    _message_args = (_handle, _uint, wintypes.WPARAM, wintypes.LPARAM)
    _subclass = ctypes.WINFUNCTYPE(_long_ptr, *_message_args, _size_t, _size_t)
    _add_subclass = _api(_comctl32, "SetWindowSubclass", _bool, _handle, _subclass, _size_t, _size_t)
    _remove_subclass = _api(_comctl32, "RemoveWindowSubclass", _bool, _handle, _subclass, _size_t)
    _default = _api(_comctl32, "DefSubclassProc", _long_ptr, *_message_args)
    _style_suffix = "PtrW" if ctypes.sizeof(_ptr) == 8 else "W"
    _get_style = _api(_user32, "GetWindowLong" + _style_suffix, _long_ptr, _handle, _int)
    _set_style = _api(_user32, "SetWindowLong" + _style_suffix, _long_ptr, _handle, _int, _long_ptr)
    _get_rect = _api(_user32, "GetWindowRect", _bool, _handle, ctypes.POINTER(wintypes.RECT))
    _get_client_rect = _api(_user32, "GetClientRect", _bool, _handle, ctypes.POINTER(wintypes.RECT))
    _zoomed = _api(_user32, "IsZoomed", _bool, _handle)
    _monitor = _api(_user32, "MonitorFromWindow", _handle, _handle, wintypes.DWORD)
    _monitor_info = _api(_user32, "GetMonitorInfoW", _bool, _handle, ctypes.POINTER(_Monitor))
    _create_dc = _api(_gdi32, "CreateCompatibleDC", _handle, _handle)
    _delete_dc = _api(_gdi32, "DeleteDC", _bool, _handle)
    _select_object = _api(_gdi32, "SelectObject", _handle, _handle, _handle)
    _delete_object = _api(_gdi32, "DeleteObject", _bool, _handle)
    _create_bitmap = _api(
        _gdi32, "CreateDIBSection", _handle, _handle, ctypes.POINTER(_BitmapInfo),
        _uint, ctypes.POINTER(_ptr), _handle, wintypes.DWORD,
    )
    _update_layer = _api(
        _user32, "UpdateLayeredWindowIndirect", _bool, _handle, ctypes.POINTER(_LayerUpdate),
    )

    _dpi_v2 = getattr(_user32, "SetProcessDpiAwarenessContext", None)
    if _dpi_v2 is not None:
        _dpi_v2.argtypes = (ctypes.c_void_p,)
        _dpi_v2.restype = wintypes.BOOL
    _user32.SetProcessDPIAware.restype = wintypes.BOOL
    _user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
    _user32.GetCursorPos.restype = wintypes.BOOL
    _user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    _user32.SetCursorPos.restype = wintypes.BOOL


def set_dpi_awareness() -> None:
    if sys.platform == "win32" and (_dpi_v2 is None or not _dpi_v2(PER_MONITOR_AWARE_V2)):
        _user32.SetProcessDPIAware()


def cursor_position() -> tuple[int, int] | None:
    if sys.platform == "win32":
        point = wintypes.POINT()
        if _user32.GetCursorPos(ctypes.byref(point)):
            return point.x, point.y
    return None


def restore_cursor(position: tuple[int, int] | None) -> None:
    if sys.platform == "win32" and position is not None:
        _user32.SetCursorPos(*position)


class LayeredFrame:
    """Present a BGRA canvas and keep drag/resize hit tests native."""

    def __init__(self, handle: int, title_height: int, controls_width: int, captured) -> None:
        self.handle = handle
        self.title_height = title_height
        self.controls_width = controls_width
        self.captured = captured
        self.bitmap = None
        self.original_bitmap = None
        self.callback = _subclass(self._message)
        self.dc = _create_dc(None)
        if not self.dc:
            raise ctypes.WinError(ctypes.get_last_error())
        if not _add_subclass(handle, self.callback, 1, 0):
            _delete_dc(self.dc)
            raise OSError("无法设置窗口标题栏")
        ctypes.set_last_error(0)
        style = _get_style(handle, GWL_EXSTYLE) | WS_EX_LAYERED
        if not _set_style(handle, GWL_EXSTYLE, style) and (error := ctypes.get_last_error()):
            self.close()
            raise ctypes.WinError(error)

    def new_buffer(self, size: tuple[int, int]):
        w, h = size
        info = _BitmapInfo(ctypes.sizeof(_BitmapInfo), w, -h, 1, 32)
        pixels = ctypes.c_void_p()
        bitmap = _create_bitmap(self.dc, ctypes.byref(info), 0, ctypes.byref(pixels), None, 0)
        if not bitmap:
            raise ctypes.WinError(ctypes.get_last_error())
        previous = _select_object(self.dc, bitmap)
        if not previous or previous == ctypes.c_void_p(-1).value:
            _delete_object(bitmap)
            raise OSError("无法建立窗口画布")
        if self.bitmap is None:
            self.original_bitmap = previous
        else:
            _delete_object(self.bitmap)
        self.bitmap = bitmap
        return (ctypes.c_ubyte * (w * h * 4)).from_address(pixels.value)

    def client_size(self) -> tuple[int, int]:
        rect = wintypes.RECT()
        if not _get_client_rect(self.handle, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        return rect.right, rect.bottom

    def present(self, size: tuple[int, int]) -> bool:
        if self.client_size() != size:
            return False
        extent = wintypes.SIZE(*size)
        origin = wintypes.POINT(0, 0)
        blend = _Blend(0, 0, 255, 1)  # AC_SRC_OVER and AC_SRC_ALPHA
        # Supply the surface extent, while letting Windows reject stale resize frames.
        update = _LayerUpdate(
            struct_size=ctypes.sizeof(_LayerUpdate),
            extent=ctypes.pointer(extent),
            source_dc=self.dc,
            origin=ctypes.pointer(origin),
            blend=ctypes.pointer(blend),
            flags=ULW_ALPHA | ULW_EX_NORESIZE,
        )
        if not _update_layer(self.handle, ctypes.byref(update)):
            error = ctypes.get_last_error()
            if self.client_size() != size:
                return False
            raise ctypes.WinError(error)
        return True

    def close(self) -> None:
        _remove_subclass(self.handle, self.callback, 1)
        if self.bitmap is not None:
            _select_object(self.dc, self.original_bitmap)
            _delete_object(self.bitmap)
        _delete_dc(self.dc)

    def _message(self, hwnd, message, wparam, lparam, _id, _data):
        if message == WM_NCHITTEST:
            if self.captured():
                return HTCLIENT
            rect = wintypes.RECT()
            if _get_rect(hwnd, ctypes.byref(rect)):
                x = ctypes.c_short(lparam & 0xFFFF).value - rect.left
                y = ctypes.c_short((lparam >> 16) & 0xFFFF).value - rect.top
                w, h = rect.right - rect.left, rect.bottom - rect.top
                if 0 <= x < w and 0 <= y < h:
                    if not _zoomed(hwnd):
                        edge_x = -1 if x < 5 else 1 if x >= w - 5 else 0
                        edge_y = -1 if y < 5 else 1 if y >= h - 5 else 0
                        if edge_x or edge_y:
                            return RESIZE_HITS[edge_x, edge_y]
                    return HTCAPTION if y < self.title_height and x < w - self.controls_width else HTCLIENT
        result = _default(hwnd, message, wparam, lparam)
        if message == WM_GETMINMAXINFO:
            monitor = _Monitor(size=ctypes.sizeof(_Monitor))
            if _monitor_info(_monitor(hwnd, 2), ctypes.byref(monitor)):
                info = _MinMax.from_address(lparam)
                work, bounds = monitor.work, monitor.bounds
                info.max_position = wintypes.POINT(work.left - bounds.left, work.top - bounds.top)
                info.max_size = wintypes.POINT(work.right - work.left, work.bottom - work.top)
        return result

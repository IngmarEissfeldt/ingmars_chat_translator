#Written by AI

import ctypes
from ctypes import wintypes

import win32api
import win32con
import win32gui


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class RGBQUAD(ctypes.Structure):
    _fields_ = [
        ("rgbBlue", ctypes.c_ubyte),
        ("rgbGreen", ctypes.c_ubyte),
        ("rgbRed", ctypes.c_ubyte),
        ("rgbReserved", ctypes.c_ubyte),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", RGBQUAD * 1),
    ]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


_gdi32 = ctypes.windll.gdi32
_user32 = ctypes.windll.user32

_gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
]
_gdi32.CreateDIBSection.restype = wintypes.HBITMAP

_user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND,
    wintypes.HDC,
    ctypes.POINTER(wintypes.POINT),
    ctypes.POINTER(wintypes.SIZE),
    wintypes.HDC,
    ctypes.POINTER(wintypes.POINT),
    wintypes.COLORREF,
    ctypes.POINTER(BLENDFUNCTION),
    wintypes.DWORD,
]
_user32.UpdateLayeredWindow.restype = wintypes.BOOL


class Overlay:
    """
    Click-through, always-on-top overlay. Each text item is drawn on
    its own 90%-opacity black box sized to fit it; everywhere else on
    screen stays fully transparent. Excluded from screen capture
    (dxcam, OBS, etc.) so it doesn't get picked up by your own
    screenshot/OCR loop.

    Coordinates given to add_text/update_text are the top-left of the
    TEXT (padding is added automatically around it for the box).

    Example:
        overlay = Overlay()
        id1 = overlay.add_text("Hello", 100, 100)
        overlay.show()
        overlay.update_text(id1, "Goodbye", 200, 150)
        overlay.destroy()
    """

    WDA_EXCLUDEFROMCAPTURE = 0x00000011
    ULW_ALPHA = 0x00000002
    AC_SRC_OVER = 0x00
    AC_SRC_ALPHA = 0x01

    BOX_ALPHA = 229
    BOX_PADDING_X = 6   # horizontal padding, unchanged
    BOX_PADDING_Y = 2   # vertical padding, tightened
    TEXT_COLOR = (255, 255, 255)
    FONT_HEIGHT = -20
    FONT_NAME = "Segoe UI"

    def __init__(self):
        self.hwnd = None

        # {id: {"text": str, "x": int, "y": int}}
        self._texts = {}
        self._next_id = 0

        self._class_name = "OCRTextOverlay"
        self._hinstance = win32api.GetModuleHandle(None)

        self._screen_x = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
        self._screen_y = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
        self._screen_w = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        self._screen_h = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)

        self._font_cache = {}

        self._visible = False

        self._register_window_class()
        self._create_window()
        self._exclude_from_capture()

    # ------------------------------------------------------------------
    # Window setup
    # ------------------------------------------------------------------

    def _create_font(self):
        lf = win32gui.LOGFONT()
        lf.lfHeight = self.FONT_HEIGHT
        lf.lfWeight = win32con.FW_NORMAL
        # Grayscale AA, not ClearType — keeps R==G==B so we can use a
        # single channel as a clean luminance/alpha mask.
        lf.lfQuality = win32con.ANTIALIASED_QUALITY
        lf.lfCharSet = win32con.DEFAULT_CHARSET
        lf.lfFaceName = self.FONT_NAME
        return win32gui.CreateFontIndirect(lf)

    
    def _get_font(self, pixel_height):
        """
        Return a cached font at the given pixel height, creating it if
        needed, so text renders crisp at its actual target size instead
        of being scaled from a fixed base size.
        """
        pixel_height = max(1, int(pixel_height))
        font = self._font_cache.get(pixel_height)
        if font is None:
            lf = win32gui.LOGFONT()
            lf.lfHeight = -pixel_height  # negative = pixel height
            lf.lfWeight = win32con.FW_NORMAL
            lf.lfQuality = win32con.ANTIALIASED_QUALITY
            lf.lfCharSet = win32con.DEFAULT_CHARSET
            lf.lfFaceName = self.FONT_NAME
            font = win32gui.CreateFontIndirect(lf)
            self._font_cache[pixel_height] = font
        return font

    def _register_window_class(self):
        window_class = win32gui.WNDCLASS()
        window_class.lpfnWndProc = self._window_proc
        window_class.lpszClassName = self._class_name
        window_class.hInstance = self._hinstance
        self._class_atom = win32gui.RegisterClass(window_class)

    def _create_window(self):
        extended_style = (
            win32con.WS_EX_LAYERED
            | win32con.WS_EX_TRANSPARENT
            | win32con.WS_EX_TOPMOST
            | win32con.WS_EX_NOACTIVATE
            | win32con.WS_EX_TOOLWINDOW
        )

        self.hwnd = win32gui.CreateWindowEx(
            extended_style,
            self._class_atom,
            "",
            win32con.WS_POPUP,
            self._screen_x,
            self._screen_y,
            self._screen_w,
            self._screen_h,
            0,
            0,
            self._hinstance,
            None,
        )
        # No SetLayeredWindowAttributes here — per-pixel alpha is
        # pushed directly via UpdateLayeredWindow in _redraw().

    def _exclude_from_capture(self):
        """
        Hide this window from screen-capture APIs (including dxcam)
        so the overlay's own translated text doesn't get grabbed and
        fed back into the next OCR pass. Requires Windows 10 2004+
        (build 19041); silently no-ops on older builds.
        """
        try:
            _user32.SetWindowDisplayAffinity(
                self.hwnd, self.WDA_EXCLUDEFROMCAPTURE
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Windows message handler
    # ------------------------------------------------------------------

    def _window_proc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_DESTROY:
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_text(self, text, x1, y1, x2, y2):
        """
        Add a new text item, scaled to fill the given box.

        x1, y1, x2, y2: top-left and bottom-right of the region the
        text should cover (e.g. straight from your OCR bounding box).
        """
        text_id = self._next_id
        self._next_id += 1

        self._texts[text_id] = {
            "text": str(text),
            "x1": int(x1),
            "y1": int(y1),
            "x2": int(x2),
            "y2": int(y2),
        }

        self._redraw()
        return text_id

    def update_text(self, text_id, text=None, x1=None, y1=None, x2=None, y2=None):
        """
        Update an existing text item. Any argument left as None keeps
        its current value.
        """
        if text_id not in self._texts:
            return False

        item = self._texts[text_id]

        if text is not None:
            item["text"] = str(text)
        if x1 is not None:
            item["x1"] = int(x1)
        if y1 is not None:
            item["y1"] = int(y1)
        if x2 is not None:
            item["x2"] = int(x2)
        if y2 is not None:
            item["y2"] = int(y2)

        self._redraw()
        return True

    def remove_text(self, text_id):
        if text_id not in self._texts:
            return False
        del self._texts[text_id]
        self._redraw()
        return True

    def clear(self):
        self._texts.clear()
        self._redraw()

    def toggle(self):
        """
        Toggle overlay visibility on/off. Unlike clear(), this doesn't
        delete any text items — they reappear as-is when shown again.
        """
        if self._visible:
            self.hide()
        else:
            self.show()

    def show(self):
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
        self._visible = True

    def hide(self):
        win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
        self._visible = False

    def pump(self):
        """
        Process pending Windows messages for this window without
        blocking. Call this once per iteration of your capture/OCR/
        translate loop.
        """
        win32gui.PumpWaitingMessages()

    def start_pump_thread(self):
        import threading
        self._pump_thread = threading.Thread(
            target=win32gui.PumpMessages, daemon=True
        )
        self._pump_thread.start()

    def destroy(self):
        if self.hwnd:
            win32gui.DestroyWindow(self.hwnd)
            self.hwnd = None
        for font in self._font_cache.values():
            win32gui.DeleteObject(font)
        self._font_cache.clear()
        try:
            win32gui.UnregisterClass(self._class_name, self._hinstance)
        except win32gui.error:
            pass

    # ------------------------------------------------------------------
    # Internal helpers — per-pixel alpha compositing
    # ------------------------------------------------------------------

    def _create_dib(self, width, height):
        """
        Create a top-down 32bpp DIB section and return
        (hbitmap, pointer_to_pixel_buffer).
        """
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height  # negative = top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB

        ppv_bits = ctypes.c_void_p()
        hbitmap = _gdi32.CreateDIBSection(
            0, ctypes.byref(bmi), 0, ctypes.byref(ppv_bits), None, 0
        )
        if not hbitmap:
            raise ctypes.WinError(ctypes.get_last_error())

        return hbitmap, ppv_bits

    def _stamp_text(self, canvas, canvas_w, canvas_h, item):
        text = item["text"]
        if not text:
            return

        target_w = item["x2"] - item["x1"]
        target_h = item["y2"] - item["y1"]
        if target_w <= 0 or target_h <= 0:
            return

        # Render at a font size matched to the box height so glyphs are
        # crisp, rather than rendering small and stretching (which is
        # what caused the pixelation).
        font = self._get_font(target_h)

        hdc_scratch = win32gui.CreateCompatibleDC(0)
        old_font = win32gui.SelectObject(hdc_scratch, font)
        natural_w, natural_h = win32gui.GetTextExtentPoint32(hdc_scratch, text)

        metrics = win32gui.GetTextMetrics(hdc_scratch)
        internal_leading = metrics["InternalLeading"]
        natural_h -= internal_leading

        win32gui.SelectObject(hdc_scratch, old_font)
        win32gui.DeleteDC(hdc_scratch)

        if natural_w <= 0 or natural_h <= 0:
            return

        mask_hbitmap, mask_ptr = self._create_dib(natural_w, natural_h)
        mask_size = natural_w * natural_h * 4
        ctypes.memset(mask_ptr, 0xFF, mask_size)

        mask_hdc = win32gui.CreateCompatibleDC(0)
        win32gui.SelectObject(mask_hdc, mask_hbitmap)
        win32gui.SelectObject(mask_hdc, font)
        win32gui.SetBkMode(mask_hdc, win32con.TRANSPARENT)
        win32gui.SetTextColor(mask_hdc, win32api.RGB(0, 0, 0))
        win32gui.ExtTextOut(mask_hdc, 0, -internal_leading, 0, None, text)
        win32gui.DeleteDC(mask_hdc)

        mask = (ctypes.c_ubyte * mask_size).from_address(mask_ptr.value)

        pad_x = self.BOX_PADDING_X
        pad_y = self.BOX_PADDING_Y
        box_w = target_w + pad_x * 2
        box_h = target_h + pad_y * 2

        box_x = item["x1"] - self._screen_x - pad_x
        box_y = item["y1"] - self._screen_y - pad_y

        box_alpha = self.BOX_ALPHA
        tr, tg, tb = self.TEXT_COLOR

        for row in range(box_h):
            dst_y = box_y + row
            if dst_y < 0 or dst_y >= canvas_h:
                continue

            # Vertical: 1:1 mapping now (natural_h ≈ target_h since the
            # font was rendered at that height), no vertical stretching.
            text_row = row - pad_y
            in_text_rows = 0 <= text_row < natural_h

            for col in range(box_w):
                dst_x = box_x + col
                if dst_x < 0 or dst_x >= canvas_w:
                    continue

                # Horizontal: still nearest-neighbor stretched to fill
                # the exact box width, since glyph width varies by text
                # length and must match the OCR box.
                text_col = col - pad_x
                if in_text_rows and 0 <= text_col < target_w:
                    src_col = text_col * natural_w // target_w
                    mi = (text_row * natural_w + src_col) * 4
                    luminance = mask[mi]
                    alpha_text = 255 - luminance
                else:
                    alpha_text = 0

                out_alpha = alpha_text + box_alpha * (255 - alpha_text) // 255
                out_b = (tb * alpha_text) // 255
                out_g = (tg * alpha_text) // 255
                out_r = (tr * alpha_text) // 255

                di = (dst_y * canvas_w + dst_x) * 4
                canvas[di + 0] = out_b
                canvas[di + 1] = out_g
                canvas[di + 2] = out_r
                canvas[di + 3] = out_alpha

        win32gui.DeleteObject(mask_hbitmap)

    def _redraw(self):
        if not self.hwnd:
            return

        width, height = self._screen_w, self._screen_h
        buf_size = width * height * 4

        hbitmap, ppv_bits = self._create_dib(width, height)
        ctypes.memset(ppv_bits, 0, buf_size)  # fully transparent by default
        canvas = (ctypes.c_ubyte * buf_size).from_address(ppv_bits.value)

        for item in self._texts.values():
            self._stamp_text(canvas, width, height, item)

        hdc_mem = win32gui.CreateCompatibleDC(0)
        win32gui.SelectObject(hdc_mem, hbitmap)
        hdc_screen = win32gui.GetDC(0)

        blend = BLENDFUNCTION()
        blend.BlendOp = self.AC_SRC_OVER
        blend.BlendFlags = 0
        blend.SourceConstantAlpha = 255
        blend.AlphaFormat = self.AC_SRC_ALPHA

        dst_pt = wintypes.POINT(self._screen_x, self._screen_y)
        src_pt = wintypes.POINT(0, 0)
        win_size = wintypes.SIZE(width, height)

        _user32.UpdateLayeredWindow(
            self.hwnd,
            hdc_screen,
            ctypes.byref(dst_pt),
            ctypes.byref(win_size),
            hdc_mem,
            ctypes.byref(src_pt),
            0,
            ctypes.byref(blend),
            self.ULW_ALPHA,
        )

        win32gui.ReleaseDC(0, hdc_screen)
        win32gui.DeleteDC(hdc_mem)
        win32gui.DeleteObject(hbitmap)
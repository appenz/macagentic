"""Quartz screenshot capture."""

import Quartz
from AppKit import NSBitmapImageRep, NSPNGFileType


def find_window(title_substring: str) -> int | None:
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly,
        Quartz.kCGNullWindowID,
    )
    for window in windows:
        title = window.get("kCGWindowName") or ""
        if title_substring in title:
            return window.get("kCGWindowNumber")
    return None


def capture_window(window_id: int, output_path: str) -> bool:
    image = Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull,
        Quartz.kCGWindowListOptionIncludingWindow,
        window_id,
        Quartz.kCGWindowImageBoundsIgnoreFraming,
    )
    if image is None:
        return False
    bitmap = NSBitmapImageRep.alloc().initWithCGImage_(image)
    data = bitmap.representationUsingType_properties_(NSPNGFileType, None)
    if data is None:
        return False
    data.writeToFile_atomically_(output_path, True)
    return True


def capture_window_by_title(
    title_substring: str,
    output_path: str,
) -> bool:
    window_id = find_window(title_substring)
    return (
        window_id is not None
        and capture_window(window_id, output_path)
    )

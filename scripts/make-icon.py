"""Render the 🎙 emoji into LocalFlow.icns. Run under the project venv
(needs PyObjC). Usage: python scripts/make-icon.py <output-dir>"""

import subprocess
import sys
import tempfile
from pathlib import Path

from AppKit import (
    NSBitmapImageRep,
    NSFont,
    NSFontAttributeName,
    NSGraphicsContext,
    NSImage,
    NSMakeRect,
    NSPNGFileType,
    NSString,
)

SIZE = 1024


def render_base_png(path: Path) -> None:
    image = NSImage.alloc().initWithSize_((SIZE, SIZE))
    image.lockFocus()
    text = NSString.stringWithString_("🎙")
    attrs = {NSFontAttributeName: NSFont.systemFontOfSize_(SIZE * 0.78)}
    bounds = text.sizeWithAttributes_(attrs)
    text.drawInRect_withAttributes_(
        NSMakeRect((SIZE - bounds.width) / 2, (SIZE - bounds.height) / 2, bounds.width, bounds.height),
        attrs,
    )
    rep = NSBitmapImageRep.alloc().initWithFocusedViewRect_(NSMakeRect(0, 0, SIZE, SIZE))
    image.unlockFocus()
    rep.representationUsingType_properties_(NSPNGFileType, None).writeToFile_atomically_(
        str(path), True
    )


def main() -> None:
    out_dir = Path(sys.argv[1])
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        base = tmp / "base.png"
        render_base_png(base)
        iconset = tmp / "LocalFlow.iconset"
        iconset.mkdir()
        for px in (16, 32, 64, 128, 256, 512, 1024):
            for scale, suffix in ((1, ""), (2, "@2x")):
                size = px * scale
                if size > 1024:
                    continue
                name = iconset / f"icon_{px}x{px}{suffix}.png"
                subprocess.run(
                    ["sips", "-z", str(size), str(size), str(base), "--out", str(name)],
                    check=True, capture_output=True,
                )
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(out_dir / "LocalFlow.icns")],
            check=True,
        )
    print("icon written:", out_dir / "LocalFlow.icns")


if __name__ == "__main__":
    main()

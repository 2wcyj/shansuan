from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def test_android_launcher_declares_brand_icon():
    app = ET.parse(ROOT / 'app/android/AndroidManifest.xml').getroot().find('application')
    android = '{http://schemas.android.com/apk/res/android}'
    assert app.get(android + 'icon') == '@mipmap/ic_launcher'
    assert app.get(android + 'roundIcon') == '@mipmap/ic_launcher'


def test_android_icons_use_same_master_as_desktop():
    master = Image.open(ROOT / 'app/frontend/public/brand-crop.png').convert('RGBA')
    for density, size in [('mdpi', 48), ('hdpi', 72), ('xhdpi', 96), ('xxhdpi', 144), ('xxxhdpi', 192)]:
        file = ROOT / f'app/android/res/mipmap-{density}/ic_launcher.png'
        assert file.is_file(), f'missing Android icon: {density}'
        with Image.open(file) as icon:
            assert icon.size == (size, size)
            assert icon.convert('RGBA').tobytes() == master.resize((size, size), Image.Resampling.LANCZOS).tobytes()

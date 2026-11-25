"""Build icon sizes from the supplied, temporary screenshot crop (308px).
No redrawing or replacement of the brand mark. Supply a licensed high-resolution
square master to replace public/brand-crop.png later; 512px is a compatibility
resize, not a high-resolution original.
"""
from pathlib import Path
import base64
from PIL import Image
ROOT = Path(__file__).resolve().parents[2]
def build_android_icons():
    icon=Image.open(ROOT/'app/frontend/public/brand-crop.png').convert('RGBA')
    for density,size in [('mdpi',48),('hdpi',72),('xhdpi',96),('xxhdpi',144),('xxxhdpi',192)]:
        target=ROOT/'app/android/res'/f'mipmap-{density}'
        target.mkdir(parents=True,exist_ok=True)
        icon.resize((size,size),Image.Resampling.LANCZOS).save(target/'ic_launcher.png')

def main():
    public=ROOT/'app/frontend/public'
    source=public/'brand-crop.png'
    icon=Image.open(source).convert('RGBA')
    for size in [192,512]:
        icon.resize((size,size),Image.Resampling.LANCZOS).save(public/f'icon-{size}.png')
    encoded=base64.b64encode(source.read_bytes()).decode('ascii')
    (public/'icon.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 308 308"><image width="308" height="308" href="data:image/png;base64,{encoded}"/></svg>',encoding='utf-8')
    icon.save(ROOT/'app/resources/app.ico',sizes=[(n,n) for n in [16,24,32,48,64,128,256]])
    (public/'favicon.ico').write_bytes((ROOT/'app/resources/app.ico').read_bytes())
    build_android_icons()
if __name__=='__main__':main()

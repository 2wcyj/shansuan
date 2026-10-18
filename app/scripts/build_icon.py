"""Reproducible local icon assets; no font, network or image service required."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]


def main():
    public = ROOT / 'app/frontend/public'
    public.mkdir(parents=True, exist_ok=True)
    # A bowl and three portions: a simple mark that stays readable at 16px.
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" rx="116" fill="#191e30"/>
<path d="M113 260H399C385 337 336 382 256 382S127 337 113 260Z" fill="#b9d0c4"/>
<rect x="103" y="239" width="306" height="25" rx="12.5" fill="#f0f2ea"/>
<circle cx="172" cy="184" r="18" fill="#f0f2ea"/>
<circle cx="256" cy="160" r="18" fill="#94b5a7"/>
<circle cx="340" cy="184" r="18" fill="#f0f2ea"/>
<rect x="214" y="398" width="84" height="15" rx="7.5" fill="#94b5a7"/>
</svg>'''
    (public / 'icon.svg').write_text(svg, encoding='utf-8')
    scale = 4
    icon = Image.new('RGBA', (512*scale, 512*scale))
    draw = ImageDraw.Draw(icon)
    def box(coords):return tuple(int(v*scale) for v in coords)
    draw.rounded_rectangle(box((0,0,512,512)),radius=116*scale,fill='#191e30')
    # Cubic Bezier outline sampled to match the SVG's bowl.
    points=[(113,260),(399,260)]
    for start,c1,c2,end in [((399,260),(385,337),(336,382),(256,382)),((256,382),(176,382),(127,337),(113,260))]:
        for i in range(1,101):
            t=i/100;u=1-t
            points.append(tuple(u**3*start[j]+3*u*u*t*c1[j]+3*u*t*t*c2[j]+t**3*end[j] for j in [0,1]))
    draw.polygon([(int(x*scale),int(y*scale)) for x,y in points],fill='#b9d0c4')
    draw.rounded_rectangle(box((103,239,409,264)),radius=12.5*scale,fill='#f0f2ea')
    for x,y,color in [(172,184,'#f0f2ea'),(256,160,'#94b5a7'),(340,184,'#f0f2ea')]:
        draw.ellipse(box((x-18,y-18,x+18,y+18)),fill=color)
    draw.rounded_rectangle(box((214,398,298,413)),radius=7.5*scale,fill='#94b5a7')
    icon=icon.resize((512,512),Image.Resampling.LANCZOS)
    for size in [192,512]:
        icon.resize((size,size),Image.Resampling.LANCZOS).save(public / f'icon-{size}.png')
    icon.save(ROOT / 'app/resources/app.ico',sizes=[(n,n) for n in [16,24,32,48,64,128,256]])
    (public / 'favicon.ico').write_bytes((ROOT / 'app/resources/app.ico').read_bytes())


if __name__ == '__main__':main()

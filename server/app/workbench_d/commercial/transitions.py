"""Explicit two-source transitions in premultiplied alpha; ordinary opacity stays over."""
from PIL import Image,ImageChops,ImageDraw,ImageMath


def transition(a,b,t,kind='crossfade',direction='left'):
    t=max(0,min(1,t))
    if kind=='crossfade':
        # RGBa stores RGB multiplied by alpha. Blending straight RGBA would
        # introduce fringes where the two sources have different transparency.
        bands=[ImageMath.lambda_eval(lambda e: e['convert'](e['a']*(1-t)+e['b']*t+.5,'L'),a=x.convert('F'),b=y.convert('F')) for x,y in zip(a.convert('RGBa').split(),b.convert('RGBa').split())]
        return Image.merge('RGBa',bands).convert('RGBA')
    if kind=='wipe':
        mask=Image.new('L',a.size);d=ImageDraw.Draw(mask);w,h=a.size
        rect={'left':(0,0,round(w*t),h),'right':(round(w*(1-t)),0,w,h),
              'up':(0,0,w,round(h*t)),'down':(0,round(h*(1-t)),w,h)}[direction]
        if t>0:d.rectangle(rect,fill=255)
        return Image.composite(b,a,mask)
    if kind=='push':
        w,h=a.size;out=Image.new('RGBA',a.size)
        dx,dy={'left':(-round(w*t),0),'right':(round(w*t),0),'up':(0,-round(h*t)),'down':(0,round(h*t))}[direction]
        out.alpha_composite(a,(dx,dy))
        bx=dx+(w if direction=='left' else -w if direction=='right' else 0)
        by=dy+(h if direction=='up' else -h if direction=='down' else 0)
        out.alpha_composite(b,(bx,by));return out
    raise ValueError('unsupported transition')

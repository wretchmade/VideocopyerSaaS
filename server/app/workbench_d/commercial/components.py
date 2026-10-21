"""D-owned parametric scenes and deterministic frame effects. No template imports."""
import math,random
from PIL import Image,ImageDraw,ImageFont,ImageFilter,ImageChops

SCENES=['TierBoard','Column','TopThree','DepthCard','Comment','Quiz','Chat','Explainer','TalkingHead','RichText','PathText','Ranking','LastWar','LastWarHybrid','ModelOverlay']
EFFECTS=['Flash','ColorWash','Vignette','ScanLines','DirectionalMatte','WhipVeil','GlitchVeil','Grain','LightLeak','Bokeh','TVStatic']
COMMON={'title','items','accent','background','foreground','seed','strength','direction','image','answer','subtitle','radius','text','spans','speed','columns','units','duration','path','active','reveal'}

def catalog():return dict(scenes=SCENES,effects=EFFECTS,props=sorted(COMMON),motion='frame-index deterministic; enter/reveal/depth motion',assetProps=['image'],font='explicit project font required for scenes')

def validate(layer):
    if layer.component not in SCENES+EFFECTS:raise ValueError('unknown D component')
    if set(layer.props)-COMMON:raise ValueError('unknown component properties')
    if layer.component in SCENES and not layer.fonts:raise ValueError('component text needs explicit font asset')
    if not 0<=float(layer.props.get('strength',.6))<=1:raise ValueError('strength outside 0..1')
    if len(layer.props.get('items',[]))>100 or len(layer.props.get('units',[]))>100:raise ValueError('component supports at most 100 items')

def draw(raster,layer,frame):
    validate(layer);p=layer.props;w,h=layer.width,layer.height;kind=layer.component
    age=frame-layer.start;t=age/max(1,layer.end-layer.start-1);rng=random.Random(int(p.get('seed',7))+frame)
    im=Image.new('RGBA',(w,h));d=ImageDraw.Draw(im);accent=p.get('accent','#50d4b2');fg=p.get('foreground','#f6f5ef');bg=p.get('background','#142434')
    strength=float(p.get('strength',.6));a=round(255*strength)
    if kind in EFFECTS:
        if kind=='Flash':d.rectangle((0,0,w,h),fill=(255,255,255,round(a*math.sin(math.pi*t)**2)))
        elif kind=='ColorWash':
            from PIL import ImageColor
            d.rectangle((0,0,w,h),fill=(*ImageColor.getrgb(accent),a))
        elif kind=='Vignette':
            mask=Image.new('L',(w,h));mask.putdata([round(a*min(1,(((x-w/2)/(w/2))**2+((y-h/2)/(h/2))**2)**1.4)) for y in range(h) for x in range(w)])
            im.putalpha(mask)
        elif kind=='ScanLines':
            for y in range((age%4)-4,h,4):d.line((0,y,w,y),fill=(0,0,0,a),width=1)
        elif kind=='DirectionalMatte':
            extent=round(w*t);box=(0,0,extent,h) if p.get('direction','left')=='left' else (w-extent,0,w,h);d.rectangle(box,fill=accent)
        elif kind=='WhipVeil':
            x=int((w*1.6)*t-w*.3);d.polygon([(x-w//3,0),(x,0),(x+w//3,h),(x,h)],fill=(245,245,255,a));im=im.filter(ImageFilter.GaussianBlur(max(1,w/80)))
        elif kind=='GlitchVeil':
            for _ in range(12):
                y=rng.randrange(h);x=rng.randrange(w);d.rectangle((x,y,min(w,x+w//3),min(h,y+rng.randrange(1,10))),fill=rng.choice([(255,20,100,a),(0,220,255,a)]))
        elif kind in ('Grain','TVStatic'):
            factor=1 if kind=='TVStatic' else 3
            small=Image.new('RGBA',(max(1,w//factor),max(1,h//factor)));small.putdata([(v,v,v,a) for v in [rng.randrange(256) for _ in range(small.width*small.height)]]);im=small.resize((w,h))
        elif kind=='LightLeak':
            x=int(w*(.2+.6*t));d.ellipse((x-w//2,-h//2,x+w//2,h*1.5),fill=(255,100,30,a));im=im.filter(ImageFilter.GaussianBlur(max(1,w/6)))
        elif kind=='Bokeh':
            for i in range(16):
                r=rng.uniform(.015,.08)*w;x=(i*.173*w+age*2)%w;y=(i*.317*h-age)%h;d.ellipse((x-r,y-r,x+r,y+r),fill=(255,225,180,a//2))
            im=im.filter(ImageFilter.GaussianBlur(max(1,w/120)))
        return im
    asset=raster.assets.get(layer.fonts[0])
    if not asset or asset.kind!='font':raise ValueError('component font missing')
    font=ImageFont.truetype(asset.path,max(8,layer.font_size));small=ImageFont.truetype(asset.path,max(8,round(layer.font_size*.68)))
    pad=max(8,w//25);enter=min(1,age/max(1,float(p.get('duration',12))));ease=1-(1-enter)**3
    def text(x,y,s,f=small,color=fg):
        # Validate fallback coverage; use the shared baseline renderer for every run.
        from .schema import Layer
        from .typography import caption
        box=Layer(id='label',kind='text',end=1,width=max(1,w-int(x)-pad),height=max(1,h-int(y)),text=str(s),fonts=layer.fonts,font_size=f.size,color=color)
        im.alpha_composite(caption(raster,box,0),(int(x),int(y)))
    def panel(box,color=bg):d.rounded_rectangle(tuple(round(v) for v in box),radius=max(4,pad//2),fill=color)
    def picture(box):
        source=raster.images.get(p.get('image'))
        if source is None and layer.id in raster.videos:
            with Image.open(raster.videos[layer.id]/f'{frame-layer.start:08d}.png') as decoded:source=decoded.convert('RGBA')
        if source:
            from PIL import ImageOps
            x,y,x2,y2=map(int,box);im.alpha_composite(ImageOps.fit(source,(max(1,x2-x),max(1,y2-y))), (x,y))
    items=p.get('items',[]);items=[{'label':v,'value':1} if isinstance(v,str) else v for v in items]
    title=p.get('title',kind)
    if kind in ('TierBoard','Column','TopThree','Ranking'):
        panel((0,0,w,h));text(pad,pad,title,font);top=pad*2+font.size*1.4;available=h-top-pad
        if kind in ('TierBoard','Ranking'):
            step=available/max(1,len(items));maximum=max([float(i.get('value',1)) for i in items]+[1])
            for n,item in enumerate(items):
                y=top+n*step;length=(w-pad*3)*float(item.get('value',1))/maximum*ease
                panel((pad,y,pad+max(1,length if kind=='Ranking' else (w-pad*2)*ease),y+step*.78),item.get('color',accent));text(pad*1.3,y+4,f'{n+1 if kind=="Ranking" else chr(65+n)}  {item.get("label","")}',color='#142434')
                if kind=='TierBoard':d.rectangle((pad,y,pad*1.2,y+step*.78),fill=fg)
        else:
            if kind=='TopThree':
                items=items[:3]
                if len(items)==3:items=[items[1],items[0],items[2]]
            column=(w-pad*2)/max(1,len(items));maximum=max([float(i.get('value',1)) for i in items]+[1])
            for n,item in enumerate(items):
                x=pad+n*column;bar=available*.7*float(item.get('value',1))/maximum*ease;y=h-pad-small.size*2-bar
                panel((x+3,y,x+column-3,h-pad-small.size*2),accent);text(x+5,h-pad-small.size*1.8,item.get('label',''))
                if kind=='TopThree':d.ellipse((x+column*.35,y-14,x+column*.65,y+4),fill='#ffd576')
    elif kind in ('DepthCard','Comment','ModelOverlay'):
        offset=round((1-ease)*pad*2);d.rounded_rectangle((pad+6,pad+offset+8,w-pad+6,h-pad+8),radius=pad,fill='#00000070');panel((pad,pad+offset,w-pad,h-pad))
        picture((pad*2,pad*2,w//3,h-pad*2));x=w//3+pad if p.get('image') else pad*2
        text(x,pad*2+offset,title,font);text(x,pad*3+font.size*1.4,p.get('subtitle',''))
        if kind=='Comment':d.polygon([(pad*2,h-pad-2),(pad*2,h-2),(pad*4,h-pad-2)],fill=bg);d.ellipse((w-pad*3,pad*2,w-pad*2,pad*3),fill=accent)
        if kind=='ModelOverlay':d.rectangle((pad,pad+offset,pad+5,h-pad),fill=accent);d.line((pad*2,h-pad*2,w-pad*2,h-pad*2),fill=accent,width=2)
    elif kind=='Quiz':
        panel((0,0,w,h));text(pad,pad,title,font);step=(h-pad*4-font.size*2)/max(1,len(items));top=pad*2+font.size*1.8
        for n,item in enumerate(items):
            active=n==p.get('answer') and t>=float(p.get('reveal',.65));y=top+step*n
            panel((pad,y,w-pad,y+step*.8),accent if active else '#304455');text(pad*2,y+4,item.get('label',''),color='#142434' if active else fg)
    elif kind=='Chat':
        panel((0,0,w,h));step=(h-pad*2)/max(1,len(items))
        for n,item in enumerate(items):
            if t<float(item.get('at',n/max(1,len(items)))):continue
            left=pad if n%2==0 else w//4;y=pad+n*step;panel((left,y,left+w*.7,y+step*.8),bg if n%2==0 else '#285f63');text(left+pad,y+4,item.get('label',''))
    elif kind=='Explainer':
        panel((0,0,w,h));text(pad,pad,title,font);count=max(1,len(items));cx=w/2;cy=h*.6;r=min(w,h)*.25
        for n,item in enumerate(items):
            angle=2*math.pi*n/count-math.pi/2;x=cx+math.cos(angle)*r;y=cy+math.sin(angle)*r
            d.line((cx,cy,x,y),fill=accent,width=3);d.ellipse((x-8,y-8,x+8,y+8),fill=accent);text(max(pad,x-30),max(pad,y+12),item.get('label',''))
        d.ellipse((cx-12,cy-12,cx+12,cy+12),fill=fg)
    elif kind=='TalkingHead':
        panel((0,0,w,h));picture((pad,pad,w-pad,h-pad));panel((pad,h*.7,w-pad,h-pad),'#142434df');text(pad*2,h*.73,title,font)
    elif kind=='RichText':
        x=pad;y=pad
        for span in p.get('spans',[{'text':p.get('text',title),'color':fg}]):
            for word in str(span['text']).split(' '):
                width=font.getlength(word+' ')
                if x+width>w-pad:x=pad;y+=font.size*1.6
                text(x,y,word,font,span.get('color',fg));x+=width
    elif kind=='PathText':
        value=p.get('text',title);radius=float(p.get('radius',min(w,h)*.32));width=font.getlength(value);angle=-math.pi/2-width/(2*radius)
        for char in value:
            advance=font.getlength(char);theta=angle+advance/(2*radius);tile=Image.new('RGBA',(font.size*3,font.size*3));ImageDraw.Draw(tile).text((tile.width/2,tile.height/2),char,font=font,fill=fg,anchor='mm')
            tile=tile.rotate(-math.degrees(theta)-90,resample=Image.Resampling.BICUBIC);im.alpha_composite(tile,(round(w/2+radius*math.cos(theta)-tile.width/2),round(h/2+radius*math.sin(theta)-tile.height/2)));angle+=advance/radius
    elif kind in ('LastWar','LastWarHybrid'):
        panel((0,0,w,h),'#172c23');cell=max(12,w//12)
        for x in range(0,w,cell):d.line((x,0,x,h),fill='#294438')
        for y in range(0,h,cell):d.line((0,y,w,y),fill='#294438')
        for n,u in enumerate(p.get('units',[])):
            x=float(u.get('x',.2))*w+float(u.get('dx',0))*w*ease;y=float(u.get('y',.5))*h+float(u.get('dy',0))*h*ease;r=cell*.3
            d.polygon([(x,y-r),(x+r,y+r),(x-r,y+r)],fill=u.get('color',accent));d.rectangle((x-r,y-r-5,x+r*float(u.get('health',1)),y-r-3),fill='#91df76')
        text(pad,pad,title,font)
        if kind=='LastWarHybrid':
            panel((w*.63,h*.52,w-pad+3,h-pad+3),'#f6f5ef');picture((w*.65,h*.55,w-pad,h-pad))
    return im

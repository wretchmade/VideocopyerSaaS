"""D text layout: font runs share a line baseline, including fallback faces."""
from PIL import Image,ImageDraw,ImageFont,ImageChops,ImageColor


def caption(raster,layer,frame):
    image=Image.new('RGBA',(layer.width,layer.height));draw=ImageDraw.Draw(image)
    tokens=[(w.text,layer.highlight if w.start<=frame<w.end else layer.color) for w in layer.words] if layer.words else [(layer.text,layer.color)]
    margin=layer.stroke+max(abs(v) for v in layer.shadow)
    lines=[[]]
    def width(glyphs):
        return sum(font.getlength(text) for text,font,colors in runs(glyphs))
    def runs(glyphs):
        result=[]
        for char,font,color in glyphs:
            if result and result[-1][1] is font:
                text,_,colors=result[-1];result[-1]=(text+char,font,colors+[color])
            else:result.append((char,font,[color]))
        return result
    for text,color in tokens:
        for char in text:
            if char=='\n':lines.append([]);continue
            fid=next((fid for fid in layer.fonts if char.isspace() or ord(char) in raster.fonts[fid]),None)
            if fid is None:raise ValueError(f'{layer.id}: missing glyph U+{ord(char):04X}')
            key=(fid,layer.font_size)
            if key not in raster.fonts:raster.fonts[key]=ImageFont.truetype(raster.assets[fid].path,layer.font_size)
            glyph=(char,raster.fonts[key],color)
            if width([glyph])>layer.width-2*margin:raise ValueError(f'{layer.id}: glyph wider than text box')
            if width(lines[-1]+[glyph])>layer.width-2*margin:
                moved=[]
                if char in '，。！？：；、）》」』】' and len(lines[-1])>1:moved=[lines[-1].pop()]
                lines.append(moved)
            lines[-1].append(glyph)
    layouts=[];baseline=0;top=0;bottom=0
    for index,line in enumerate(lines):
        spans=runs(line);line_width=width(line)
        x=margin if layer.text_align=='left' else (layer.width-line_width)/2 if layer.text_align=='center' else layer.width-margin-line_width
        ascent=max((f.getmetrics()[0] for _,f,_ in spans),default=layer.font_size)
        descent=max((f.getmetrics()[1] for _,f,_ in spans),default=0)
        if index:baseline+=max(previous_descent+ascent,layer.font_size)+layer.line_spacing
        previous_descent=descent
        for text,font,colors in spans:
            box=draw.textbbox((x,baseline),text,font=font,anchor='ls',stroke_width=layer.stroke)
            top=min(top,box[1]+min(0,layer.shadow[1]));bottom=max(bottom,box[3]+max(0,layer.shadow[1]))
            layouts.append((x,baseline,text,font,colors));x+=font.getlength(text)
    height=bottom-top
    if height+2*margin>layer.height:raise ValueError(f'{layer.id}: text overflow')
    offset=(margin if layer.vertical_align=='top' else (layer.height-height)/2 if layer.vertical_align=='middle' else layer.height-margin-height)-top
    for x,y,text,font,colors in layouts:
        y+=offset
        if layer.shadow!=(0,0):draw.text((x+layer.shadow[0],y+layer.shadow[1]),text,font=font,fill=layer.shadow_color,anchor='ls',stroke_width=layer.stroke,stroke_fill=layer.shadow_color)
        mask=Image.new('L',image.size);md=ImageDraw.Draw(mask);md.text((x,y),text,font=font,fill=255,anchor='ls')
        if layer.stroke:
            outline=Image.new('L',image.size);ImageDraw.Draw(outline).text((x,y),text,font=font,fill=255,anchor='ls',stroke_width=layer.stroke,stroke_fill=255)
            stroke_image=Image.new('RGBA',image.size,layer.stroke_color);alpha=ImageChops.subtract(outline,mask)
            opacity=ImageColor.getcolor(layer.stroke_color,'RGBA')[3]
            stroke_image.putalpha(alpha.point(lambda v:round(v*opacity/255)));image.alpha_composite(stroke_image)
        ink=Image.new('RGBA',image.size,colors[0]);idraw=ImageDraw.Draw(ink)
        for i,color in enumerate(colors):
            left=x+font.getlength(text[:i]);right=x+font.getlength(text[:i+1])
            idraw.rectangle((round(left),0,round(right),image.height),fill=color)
        ink.putalpha(ImageChops.multiply(ink.getchannel('A'),mask));image.alpha_composite(ink)
    return image

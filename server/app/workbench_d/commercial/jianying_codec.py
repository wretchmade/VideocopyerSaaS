"""Isolated optional Apache-2.0 pyJianYingDraft serializer, never editor automation.

Native geometry remains subject to real editor acceptance. D sources are retained.
"""
from pathlib import Path
from fractions import Fraction
import json,sys,shutil
from importlib.metadata import version


def encode(document,folder):
    if version('pyJianYingDraft')!='0.3.1':raise ValueError('audited pyJianYingDraft 0.3.1 required')
    import pyJianYingDraft as jy
    from PIL import ImageColor
    from pyJianYingDraft import assets as templates
    fps=Fraction(document['fps']['num'],document['fps']['den']);w=document['width'];h=document['height']
    clock=lambda frame:round(Fraction(frame*1000000,1)/fps)
    interval=lambda start,end:jy.Timerange(clock(start),clock(end)-clock(start))
    script=jy.ScriptFile(w,h,round(fps),False)
    assets={a['id']:a for a in document['assets']};fonts={};mapping=[]
    for layer in document['layers']:
        lw,lh=layer['width'],layer['height']
        cx=lambda x:2*(x+lw/2-w/2)/w
        cy=lambda y:-2*(y+lh/2-h/2)/h
        clip=jy.ClipSettings(alpha=layer['opacity'],rotation=layer['rotation'],scale_x=layer['scale'],scale_y=layer['scale'],transform_x=cx(layer['x']),transform_y=cy(layer['y']))
        target=interval(layer['start'],layer['end']);sx=sy=1
        if layer['kind']=='text':
            color=ImageColor.getcolor(layer['color'],'RGBA')
            style=jy.TextStyle(size=layer['font_size']/h*100,color=tuple(c/255 for c in color[:3]),alpha=color[3]/255,align={'left':0,'center':1,'right':2}[layer['text_align']],auto_wrapping=True,max_line_width=lw/w)
            segment=jy.TextSegment(layer['text'],target,style=style,clip_settings=clip)
            fonts[segment.material_id]=assets[layer['fonts'][0]]['path']
            track_type=jy.TrackType.text
        else:
            material=jy.VideoMaterial(assets[layer['asset']]['path'])
            iw,ih=material.width,material.height
            crop=layer.get('crop')
            if layer['fit']=='cover':
                x0,y0,x1,y1=crop or (0,0,iw,ih);cw,ch=x1-x0,y1-y0
                ratio=lw/lh
                if cw/ch>ratio:offset=(cw-ch*ratio)/2;x0+=offset;x1-=offset
                else:offset=(ch-cw/ratio)/2;y0+=offset;y1-=offset
                crop=(x0,y0,x1,y1)
            if crop:
                x0,y0,x1,y1=crop
                if x1>iw or y1>ih:raise ValueError('native crop exceeds material')
                material.crop_settings=jy.CropSettings(upper_left_x=x0/iw,upper_left_y=y0/ih,upper_right_x=x1/iw,upper_right_y=y0/ih,lower_left_x=x0/iw,lower_left_y=y1/ih,lower_right_x=x1/iw,lower_right_y=y1/ih)
                iw,ih=x1-x0,y1-y0
            fit=min(lw/iw,lh/ih) if layer['fit']=='contain' else max(lw/iw,lh/ih)
            native_fit=min(w/iw,h/ih)
            sx=(lw/iw if layer['fit']=='stretch' else fit)/native_fit
            sy=(lh/ih if layer['fit']=='stretch' else fit)/native_fit
            clip.scale_x=sx*layer['scale'];clip.scale_y=sy*layer['scale']
            source=interval(layer['source_start'],layer['source_start']+layer['end']-layer['start']) if layer['kind']=='video' else None
            segment=jy.VideoSegment(material,target,source_timerange=source,volume=0,clip_settings=clip)
            track_type=jy.TrackType.video
        for prop,points in layer['keyframes'].items():
            for point in points:
                value=point['value'];offset=clock(point['frame']-layer['start'])
                if prop=='scale':
                    segment.add_keyframe(jy.KeyframeProperty.scale_x,offset,sx*value);segment.add_keyframe(jy.KeyframeProperty.scale_y,offset,sy*value)
                else:
                    key={'x':'position_x','y':'position_y','opacity':'alpha','rotation':'rotation'}[prop]
                    segment.add_keyframe(getattr(jy.KeyframeProperty,key),offset,cx(value) if prop=='x' else cy(value) if prop=='y' else value)
        if layer['fade_in'] or layer['fade_out']:
            # Match the D frame envelope, including overlapping fades and the
            # last retained frame (end-1), rather than end-time minus 1 microsecond.
            for n in range(layer['start'],layer['end']):
                value=layer['opacity']
                if layer['fade_in']:value*=min(1,(n-layer['start'])/layer['fade_in'])
                if layer['fade_out']:value*=min(1,(layer['end']-1-n)/layer['fade_out'])
                segment.add_keyframe(jy.KeyframeProperty.alpha,clock(n-layer['start']),value)
        track=script.append_track(jy.TrackSpec(track_type,name=layer['id']));script.add_segment(segment,track)
        mapping.append(dict(dId=layer['id'],materialId=segment.material_id,kind=layer['kind']))
    for index,audio in enumerate(document['audio']):
        segment=jy.AudioSegment(assets[audio['asset']]['path'],interval(audio['start'],audio['end']),source_timerange=interval(audio['source_start'],audio['source_start']+audio['end']-audio['start']),volume=audio['volume'])
        if audio['fade_in'] or audio['fade_out']:segment.add_fade(clock(audio['fade_in']),clock(audio['fade_out']))
        track=script.append_track(jy.TrackSpec(jy.TrackType.audio,name='audio_'+str(index)));script.add_segment(segment,track)
    script.dump(str(folder/'draft_content.json'))
    native=json.loads((folder/'draft_content.json').read_text(encoding='utf8'))
    for text in native['materials']['texts']:
        if text['id'] in fonts:
            content=json.loads(text['content'])
            for style in content['styles']:style['font']={'path':fonts[text['id']],'id':''}
            text['content']=json.dumps(content,ensure_ascii=False);text['font_path']=fonts[text['id']]
    (folder/'draft_content.json').write_text(json.dumps(native,ensure_ascii=False),encoding='utf8')
    shutil.copyfile(templates.get_asset_path('DRAFT_META_TEMPLATE'),folder/'draft_meta_info.json')
    (folder/'d-native-map.json').write_text(json.dumps(mapping),encoding='utf8')


if __name__=='__main__':encode(json.loads(Path(sys.argv[1]).read_text(encoding='utf8')),Path(sys.argv[2]))

"""Optional isolated model runner. Invoke with a separately provisioned interpreter.

Only public model APIs/CLI contracts are used. No model implementation is bundled.
The host verifies weight and adapter hashes before entering this process.
"""
import argparse,json,os,re,sys,wave,subprocess
from pathlib import Path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);parser.add_argument('--response',required=True);args=parser.parse_args()
    request=json.loads(Path(args.request).read_text(encoding='utf8'));folder=Path(args.response).resolve().parent
    op=request['operation'];options=request['options'];settings=request['settings'];weights={w['name']:w['path'] for w in request['weights']}
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    # This opt-in runner is offline, including libraries with their own downloaders.
    import socket
    def offline(*args,**kwargs):raise RuntimeError('model runner is offline; provision all dependencies explicitly')
    socket.socket.connect=offline;socket.create_connection=offline
    if op in ('asr','forced-align'):
        import whisperx
        audio=whisperx.load_audio(request['evidence']['path']);device=settings.get('device','cpu');language=options.get('language',settings.get('language','en'))
        if op=='asr':
            model=whisperx.load_model(settings['asr_directory'],device,compute_type=settings.get('compute_type','int8'),language=language,local_files_only=True)
            segments=model.transcribe(audio,batch_size=settings.get('batch_size',4))['segments']
        else:
            text=options['text'];segments=[{'start':0.,'end':len(audio)/16000,'text':text}]
        aligner,metadata=whisperx.load_align_model(language,device,model_name=settings['alignment_directory'])
        aligned=whisperx.align(segments,aligner,metadata,audio,device,return_char_alignments=False)
        words=[{'text':w['word'],'start':w.get('start'),'end':w.get('end')} for w in aligned.get('word_segments',[])]
        if op=='forced-align':
            # Retain omitted tokens explicitly; never invent timestamps for them.
            import difflib
            authored=re.findall(r'[\u3400-\u9fff]|[^\s\u3400-\u9fff]+',options['text']);mapped=[{'text':t,'start':None,'end':None} for t in authored]
            for block in difflib.SequenceMatcher(a=authored,b=[w['text'] for w in words],autojunk=False).get_matching_blocks():
                for i in range(block.size):mapped[block.a+i]=words[block.b+i]
            words=mapped
        value={'words':words,'language':language,'alignment':'whisperx acoustic forced alignment'}
    elif op=='tts':
        import torch,numpy as np,soundfile as sf
        from kokoro import KModel,KPipeline
        model=KModel(config=weights['config'],model=weights['model']);pipeline=KPipeline(lang_code=options.get('language','a'),model=model)
        voice=torch.load(weights['voice'],map_location='cpu',weights_only=True)
        chunks=[audio.cpu().numpy() for _,_,audio in pipeline(options['text'],voice=voice,speed=float(options.get('speed',1)))]
        if not chunks:raise ValueError('TTS returned no audio')
        output=folder/'speech.wav';sf.write(output,np.concatenate(chunks),24000);value={'path':str(output)}
    elif op=='background-remove':
        from rembg import remove,new_session
        from PIL import Image
        session=new_session('u2net_custom',model_path=weights['model'])
        with Image.open(request['inputs'][0]['path']) as source:output=remove(source,session=session)
        path=folder/'cutout.png';output.save(path);value={'path':str(path)}
    elif op=='voice-convert':
        # Seed-VC itself stays in the operator's separate environment (GPL-3.0).
        if len(request['inputs'])!=2:raise ValueError('voice conversion requires source and reference audio')
        entry=Path(weights['entry']).resolve();out=folder/'voice-converted';out.mkdir(exist_ok=True)
        command=[sys.executable,str(entry),'--source',request['inputs'][0]['path'],'--target',request['inputs'][1]['path'],'--output',str(out),'--checkpoint',weights['model'],'--config',weights['config'],'--diffusion-steps',str(int(options.get('steps',25))),'--length-adjust',str(float(options.get('length_adjust',1))),'--inference-cfg-rate',str(float(options.get('guidance',.7))),'--f0-condition','False','--auto-f0-adjust','False','--semi-tone-shift','0','--fp16',str(bool(settings.get('fp16',False)))]
        # Offline environment propagates; operator must pre-provision auxiliary weights.
        shim=folder/'offline-python';shim.mkdir(exist_ok=True)
        (shim/'sitecustomize.py').write_text('import socket\ndef offline(*a,**k): raise RuntimeError("offline model environment")\nsocket.socket.connect=offline\nsocket.create_connection=offline\n')
        env={**os.environ,'PYTHONPATH':str(shim)+os.pathsep+os.environ.get('PYTHONPATH','')}
        subprocess.run(command,cwd=entry.parent,env=env,check=True,timeout=3600,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        outputs=list(out.glob('*.wav'))
        if len(outputs)!=1:raise ValueError('voice conversion must produce exactly one WAV')
        value={'path':str(outputs[0])}
    elif op=='video-segment':
        # TorchScript public recurrent interface. Carry all four states across frames.
        import torch,numpy as np
        from PIL import Image
        ffmpeg=os.environ['D_FFMPEG'];ffprobe=os.environ['D_FFPROBE'];source=request['inputs'][0]['path']
        flags={'check':True,'creationflags':getattr(subprocess,'CREATE_NO_WINDOW',0)}
        info=json.loads(subprocess.check_output([ffprobe,'-v','error','-show_streams','-of','json',source],creationflags=flags['creationflags']))
        video=next(s for s in info['streams'] if s['codec_type']=='video');rate=video['r_frame_rate']
        decoded=folder/'decoded';encoded=folder/'matted';decoded.mkdir(exist_ok=True);encoded.mkdir(exist_ok=True)
        subprocess.run([ffmpeg,'-v','error','-y','-i',source,'-vf','fps='+rate,'-start_number','0',str(decoded/'%08d.png')],**flags)
        model=torch.jit.load(weights['model'],map_location=settings.get('device','cpu')).eval();rec=[None]*4
        with torch.inference_mode():
            for file in sorted(decoded.glob('*.png')):
                rgb=np.asarray(Image.open(file).convert('RGB'),dtype=np.float32)/255
                tensor=torch.from_numpy(rgb.transpose(2,0,1)).unsqueeze(0).to(settings.get('device','cpu'))
                foreground,alpha,*rec=model(tensor,*rec,float(options.get('downsample_ratio',.25)))
                rgba=np.concatenate([foreground[0].cpu().numpy().transpose(1,2,0),alpha[0].cpu().numpy().transpose(1,2,0)],axis=2)
                Image.fromarray(np.clip(rgba*255,0,255).astype('uint8'),'RGBA').save(encoded/file.name)
        count=len(list(encoded.glob('*.png')))
        if not count:raise ValueError('video model produced no frames')
        from fractions import Fraction
        duration=str(float(Fraction(count)/Fraction(rate)));path=folder/'matted.mov'
        subprocess.run([ffmpeg,'-v','error','-y','-framerate',rate,'-i',str(encoded/'%08d.png'),'-i',source,'-map','0:v','-map','1:a?','-t',duration,'-c:v','png','-pix_fmt','rgba','-c:a','pcm_s16le',str(path)],**flags)
        value={'path':str(path),'frames':count,'fps':rate,'recurrentStates':4}
    else:raise ValueError('unsupported model operation')
    Path(args.response).write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')

if __name__=='__main__':main()

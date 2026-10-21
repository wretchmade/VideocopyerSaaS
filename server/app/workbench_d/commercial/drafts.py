"""Immutable managed drafts, explicit degradation and new-directory-only installation."""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import json,os,shutil,subprocess,re
from .schema import Project,upgrade,Layer
from .store import canonical,fingerprint,uid
from .render import sha,command,binary,Rasterizer,animated
from .production_state import checked_file
from .resources import heavy,current


def requires_companion(layer):
    """Keep export and temporal-edit capability checks on the same boundary."""
    text_effect=layer.kind=='text' and (layer.stroke or layer.shadow!=(0,0) or len(layer.fonts)>1)
    return bool(layer.brand_lock or layer.kind in ('component','rect') or text_effect or layer.transcript or layer.words or (layer.keyframes.get('opacity') and (layer.fade_in or layer.fade_out)) or any(k.easing!='linear' for points in layer.keyframes.values() for k in points))


def guard_directory(folder):
    folder=Path(folder).resolve()
    if any(folder.glob('*.lock')) or (folder/'draft.lock').exists():raise ValueError('DRAFT_LOCKED')
    if os.name=='nt':
        shell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        scan=subprocess.run([str(shell),'-NoProfile','-NonInteractive','-Command',"if (@(Get-Process -Name JianyingPro,CapCut -ErrorAction SilentlyContinue).Count -gt 0) { exit 3 }; exit 0"],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=20)
        if scan.returncode==3:raise ValueError('EDITOR_RUNNING: close the editor before importing or installing drafts')
        if scan.returncode!=0:raise ValueError('EDITOR_STATE_UNAVAILABLE: cannot safely check running editor')
    return folder


class Drafts:
    def __init__(self,engine):
        self.engine=engine;self.store=engine.store
        with self.store.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS managed_drafts(id TEXT PRIMARY KEY,name TEXT,revision INTEGER);
            CREATE TABLE IF NOT EXISTS draft_revisions(draft TEXT,revision INTEGER,spec TEXT,manifest TEXT,PRIMARY KEY(draft,revision));
            CREATE TABLE IF NOT EXISTS export_choices(id TEXT PRIMARY KEY,delivery TEXT,document TEXT);
            CREATE TABLE IF NOT EXISTS draft_installations(id TEXT PRIMARY KEY,draft TEXT,revision INTEGER,path TEXT,manifest TEXT);
            ''')

    def mutate(self,name,args,fn):return self.store.mutate(args['commandId'],{'op':name,**args},fn)

    def choose_export(self,args):
        def apply(db):
            if args['format']!='jianying':raise ValueError('only explicit jianying export is supported')
            path=self.store.root/'deliveries'/args['deliveryId']/'receipt.json'
            if not path.resolve().is_relative_to((self.store.root/'deliveries').resolve()):raise ValueError('invalid delivery identity')
            receipt=json.loads(path.read_text(encoding='utf8'));checked_file(receipt['path'],receipt['sha256']);build=self.store.build(receipt['buildId'],db)
            if receipt['projectId']!=build['project'] or receipt['revision']!=build['revision'] or receipt['sha256']!=build['result']['sha256']:raise ValueError('delivery binding mismatch')
            cid=fingerprint(args)[:32];choice=dict(choiceId=cid,delivery=receipt,format='jianying',allowBaked=args['allowBaked'])
            db.execute('INSERT INTO export_choices VALUES(?,?,?)',(cid,args['deliveryId'],canonical(choice)));return choice
        return self.mutate('choose_export',args,apply)

    @heavy
    def export_draft(self,args):
        def apply(db):
            choice=db.execute('SELECT document FROM export_choices WHERE id=?',(args['choiceId'],)).fetchone()
            if not choice:raise ValueError('export choice not found')
            choice=json.loads(choice['document']);delivery=choice['delivery'];checked_file(delivery['path'],delivery['sha256'])
            build=self.store.build(delivery['buildId'],db);doc=deepcopy(build['spec'])
            results={n['id']:n['result'] for n in build['nodes'] if n['status']=='succeeded'}
            for task in doc['tasks']:
                value=results[task['id']];checked_file(value['path'],value['sha256']);doc['assets'].append(dict(id=task['id'],kind=value['kind'],path=value['path'],sha256=value['sha256'],license='derived asset; original and provider rights apply',source='d-build:'+build['id']))
            doc['tasks']=[]
            return self.new(db,args['name'],doc,choice['allowBaked'],{'deliveryId':delivery['deliveryId'],'buildId':build['id'],'projectId':build['project'],'revision':build['revision']})
        return self.mutate('export_draft',args,apply)

    @heavy
    def create(self,args):
        def apply(db):
            p=self.store.project(args['projectId'],args['revision'],db)
            if p['document']['tasks']:raise ValueError('task-backed project requires successful build → delivery → export choice')
            return self.new(db,args['name'],p['document'],args['allowBaked'],dict(projectId=p['projectId'],revision=p['authorRevision']))
        return self.mutate('jianying_create',args,apply)

    def new(self,db,name,doc,allow_baked,source):
        did=uid();db.execute('INSERT INTO managed_drafts VALUES(?,?,0)',(did,name))
        return self.write_revision(db,did,0,doc,allow_baked,source)

    def write_revision(self,db,did,revision,document,allow_baked,source):
        folder=(self.store.root/'drafts'/did/'revisions'/str(revision)).resolve()
        if not folder.is_relative_to((self.store.root/'drafts').resolve()) or folder.exists():raise ValueError('immutable draft revision already exists or invalid')
        try:return self._write_revision(db,did,revision,document,allow_baked,source)
        except BaseException:
            # This invocation alone owns the newly created directory.
            if folder.exists():shutil.rmtree(folder)
            raise

    def _write_revision(self,db,did,revision,document,allow_baked,source):
        doc=upgrade(document);folder=self.store.root/'drafts'/did/'revisions'/str(revision);folder.mkdir(parents=True,exist_ok=False)
        exported=doc.model_dump(mode='json');media=folder/'media';media.mkdir()
        for a in exported['assets']:
            current().check()
            original=checked_file(a['path'],a['sha256']);target=media/(a['sha256']+original.suffix);shutil.copyfile(original,target);checked_file(target,a['sha256']);a['path']=str(target)
        doc=Project.model_validate(exported)
        unsupported=[]
        if doc.fps.den!=1:unsupported.append(dict(id='$clock',reason='native draft fps must be integral; source timing retained in microseconds'))
        transition_ids={id for tr in doc.transitions for id in (tr.source,tr.target)}
        for l in doc.layers:
            if requires_companion(l) or l.id in transition_ids:unsupported.append(dict(id=l.id,reason='procedural layer, fallback/styled/timed typography, nonlinear/composed motion or explicit transition requires per-layer/group companion render'))
        if unsupported and not allow_baked:raise ValueError('EXPLICIT_DEGRADATION_CHOICE_REQUIRED: '+canonical(unsupported))
        # Compile only unsupported layers/groups; never flatten the entire editable timeline.
        native=deepcopy(exported);native['transitions']=[];native['layers']=[];baked=[];consumed=set()
        generated_ids={a['id'] for a in native['assets']}|{l['id'] for l in exported['layers']}
        def generated_id(prefix):
            value=prefix[:70];index=0
            while value in generated_ids:index+=1;value=prefix[:70]+'_'+str(index)
            generated_ids.add(value);return value
        partial=doc.model_copy(deep=True)
        partial.layers=[l for l in doc.layers if requires_companion(l) and l.id not in transition_ids]
        partial.transitions=[]
        raster=Rasterizer(partial,folder/'raster',current().check);raster.prepare()
        for layer in sorted(doc.layers,key=lambda l:l.track):
            if layer.id in consumed:continue
            group={layer.id}
            if layer.id in transition_ids:
                changed=True
                while changed:
                    old=set(group)
                    for tr in doc.transitions:
                        if group&{tr.source,tr.target}:group.update((tr.source,tr.target))
                    changed=old!=group
            targets=[l for l in doc.layers if l.id in group];requires=any(u['id'] in group for u in unsupported)
            if not requires:native['layers'].append(layer.model_dump(mode='json'));continue
            consumed.update(group);start=min(l.start for l in targets);end=max(l.end for l in targets);frames=folder/('frames-'+layer.id);frames.mkdir()
            if len(group)==1 and layer.kind in ('text','image','rect') and not (layer.brand_lock or layer.words or layer.transcript or layer.keyframes or layer.fade_in or layer.fade_out):
                # One transparent state preserves the authored typography; other tracks stay native.
                path=media/(layer.id+'.png');raster.layer_image(layer,start).save(path)
                aid=generated_id('baked_'+layer.id)
                native['assets'].append(dict(id=aid,kind='image',path=str(path),sha256=sha(path),source='D static companion',license='derived from declared project assets'))
                native['layers'].append(Layer(id=layer.id,kind='image',asset=aid,start=start,end=end,width=doc.width,height=doc.height,track=layer.track,fit='stretch').model_dump(mode='json'))
                baked.append(dict(layers=sorted(group),asset=aid,editable='separate static image; styled text pixels baked, source recipe retained'))
                continue
            if len(group)>1:
                partial=doc.model_copy(deep=True);partial.background='#00000000';partial.layers=targets;partial.transitions=[t for t in doc.transitions if {t.source,t.target}<=group]
                gr=Rasterizer(partial,folder/('group-'+layer.id),current().check);gr.prepare()
            for n in range(start,end):
                current().check()
                image=gr.frame(n) if len(group)>1 else raster.layer_image(layer,n);image.save(frames/f'{n-start:08d}.png')
            path=media/(layer.id+'.mov');rate=f'{doc.fps.num}/{doc.fps.den}'
            command([binary('ffmpeg'),'-v','error','-y','-framerate',rate,'-i',frames/'%08d.png','-c:v','png','-pix_fmt','rgba',path])
            aid=generated_id('baked_'+layer.id);native['assets'].append(dict(id=aid,kind='video',path=str(path),sha256=sha(path),source='D companion render',license='derived from declared project assets'))
            native['layers'].append(Layer(id=layer.id,kind='video',asset=aid,start=start,end=end,width=doc.width,height=doc.height,track=layer.track,fit='stretch').model_dump(mode='json'));baked.append(dict(layers=sorted(group),asset=aid,editable='native companion clip remains separate; internal effect is baked; managed trim/split/move of this source recipe is rejected to preserve its clock'))
        # Explicit background is a separate editable media layer, not a flattened movie.
        from PIL import Image
        bg=media/'background.png';Image.new('RGBA',(doc.width,doc.height),doc.background).save(bg)
        background_id=generated_id('d_background');background_layer=generated_id('d_background_layer')
        native['assets'].append(dict(id=background_id,kind='image',path=str(bg),sha256=sha(bg),license='generated project color',source='project background'))
        native['layers'].insert(0,Layer(id=background_layer,kind='image',asset=background_id,end=doc.frames,width=doc.width,height=doc.height,track=min([l.track for l in doc.layers]+[0])-1).model_dump(mode='json'))
        request=folder/'native-input.json';request.write_text(canonical(native),encoding='utf8')
        python=os.environ.get('D_JIANYING_PYTHON')
        if not python or not Path(python).is_file():raise ValueError('configure isolated D_JIANYING_PYTHON with audited pyJianYingDraft 0.3.1')
        command([python,Path(__file__).with_name('jianying_codec.py'),request,folder])
        native_path=folder/'draft_content.json'
        notes=unsupported+[dict(id='$text-layout',reason='native text remains editable; font metrics and layout require real editor acceptance')] if any(l.kind=='text' for l in doc.layers) else unsupported
        notes=notes+[dict(id='$native-geometry',reason='native position, crop and animation mapping is structural; real editor visual parity is not yet verified')]
        manifest=dict(draftId=did,revision=revision,source=source,path=str(folder),nativeHash=sha(native_path),documentHash=fingerprint(exported),allowBaked=allow_baked,baked=baked,limitations=notes,editorUIVerified=False,files={p.relative_to(folder).as_posix():sha(p) for p in folder.rglob('*') if p.is_file() and (p.parent==folder or p.is_relative_to(media))})
        # Native decoder verifies this hash before trusting the portable D sidecar.
        (folder/'d-project.json').write_text(canonical(exported),encoding='utf8');manifest['files']['d-project.json']=sha(folder/'d-project.json')
        (folder/'d-manifest.json').write_text(canonical(manifest),encoding='utf8')
        db.execute('INSERT INTO draft_revisions VALUES(?,?,?,?)',(did,revision,canonical(exported),canonical(manifest)))
        return manifest

    def list(self,args):
        with self.store.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM managed_drafts ORDER BY rowid DESC')]

    def read(self,args,db):
        draft=db.execute('SELECT * FROM managed_drafts WHERE id=?',(args['draftId'],)).fetchone()
        if not draft:raise ValueError('managed draft not found')
        rev=args.get('revision',draft['revision']);row=db.execute('SELECT * FROM draft_revisions WHERE draft=? AND revision=?',(draft['id'],rev)).fetchone()
        if not row:raise ValueError('draft revision not found')
        return draft,json.loads(row['spec']),json.loads(row['manifest'])

    def integrity(self,manifest):
        root=Path(manifest['path'])
        return [relative for relative,digest in manifest['files'].items() if not (root/relative).is_file() or sha(root/relative)!=digest]

    def inspect(self,args):
        with self.store.connect() as db:draft,spec,manifest=self.read(args,db)
        changes=self.integrity(manifest);native=json.loads((Path(manifest['path'])/'draft_content.json').read_text(encoding='utf8'))
        return dict(**manifest,name=draft['name'],manualChanges=changes,tracks=[dict(id=t['id'],type=t['type'],segments=[dict(id=s['id'],materialId=s['material_id'],range=s['target_timerange']) for s in t['segments']]) for t in native['tracks']])

    @heavy
    def edit(self,args):
        def apply(db):
            draft,spec,manifest=self.read(args,db)
            if draft['revision']!=args['baseRevision']:raise ValueError('DRAFT_REVISION_CONFLICT')
            if args['expectedHash']!=manifest['nativeHash'] or self.integrity(manifest):raise ValueError('MANUAL_CHANGE_DETECTED')
            guard_directory(manifest['path']);doc=deepcopy(spec)
            for action in args['actions']:self.edit_action(doc,action)
            revision=draft['revision']+1;result=self.write_revision(db,draft['id'],revision,doc,manifest['allowBaked'],manifest['source'])
            db.execute('UPDATE managed_drafts SET revision=? WHERE id=?',(revision,draft['id']));return result
        return self.mutate('jianying_edit',args,apply)

    def edit_action(self,doc,action):
        op=action['op'];audio=action.get('target')=='audio';items=doc['audio'] if audio else doc['layers']
        index=action.get('index') if audio else next((i for i,x in enumerate(items) if x['id']==action.get('id')),None)
        if type(index)!=int or not 0<=index<len(items):raise ValueError('edit target missing')
        item=items[index]
        if not audio and any(item['id'] in (t['source'],t['target']) for t in doc['transitions']):raise ValueError('edit explicit transition group in D project before exporting')
        if op in ('trim','split','move') and not audio and requires_companion(Layer.model_validate(item)):
            raise ValueError('TEMPORAL_EDIT_UNSUPPORTED: companion-rendered layer may depend on local age or nonlinear timing; edit the original D project or explicitly import its rendered media before trimming, splitting or moving')
        if op in ('trim','split') and audio and (item['fade_in'] or item['fade_out']):
            raise ValueError('TEMPORAL_EDIT_UNSUPPORTED: audio fade envelope cannot be restarted at a cut; render/import an explicit audio asset or edit the original D project')
        if op=='delete':items.pop(index)
        elif op=='volume':
            if not audio:raise ValueError('volume edit requires audio target')
            item['volume']=action['value']
        elif op=='subtitle':
            if audio or item['kind']!='text':raise ValueError('subtitle edit requires text layer')
            item['text']=action['text'];item['words']=[];item['transcript']=None
        elif op=='crop':
            if audio:raise ValueError('crop requires visual layer')
            item['crop']=action['rect']
        elif op=='move':
            delta=action['start']-item['start'];item['start']+=delta;item['end']+=delta
            for values in item.get('keyframes',{}).values():
                for key in values:key['frame']+=delta
            for word in item.get('words',[]):word['start']+=delta;word['end']+=delta
        elif op in ('trim','split'):
            old=deepcopy(item);start=action.get('start',item['start']);end=action.get('end',item['end']);cut=action.get('frame')
            if op=='split':
                if not item['start']<cut<item['end']:raise ValueError('split must be inside segment')
                right=deepcopy(item)
                if not audio:right['id']=item['id']+'_split_'+str(cut)
                items.insert(index+1,right);end=cut
                self.trim(right,old,cut,old['end'],audio)
            self.trim(item,old,start,end,audio)
        else:raise ValueError('unsupported draft edit')
        upgrade(doc)

    def trim(self,item,old,start,end,audio):
        if not old['start']<=start<end<=old['end']:raise ValueError('trim outside segment')
        item['start']=start;item['end']=end;item['source_start']=old.get('source_start',0)+start-old['start']
        if not audio:
            layer=Layer.model_validate(old)
            for key,points in old['keyframes'].items():
                # Half-open intervals still need the last RETAINED sample. Without
                # it a cut before the next key turns the whole left side constant.
                # Pin every retained frame, not only algebraically equivalent
                # endpoints: re-interpolation can round alpha across an 8-bit
                # half-step. This also keeps repeated cuts frame-exact.
                frames=range(start,end)
                item['keyframes'][key]=[dict(frame=n,value=animated(layer,key,n),easing='linear') for n in frames]
            if old['fade_in'] or old['fade_out']:
                # Freeze the original program-relative envelope at every retained
                # frame. Restarting a segment-relative fade would change the cut.
                def opacity(n):
                    value=animated(layer,'opacity',n)
                    if layer.fade_in:value*=min(1,(n-layer.start)/layer.fade_in)
                    if layer.fade_out:value*=min(1,(layer.end-1-n)/layer.fade_out)
                    return value
                item['keyframes']['opacity']=[dict(frame=n,value=opacity(n),easing='linear') for n in range(start,end)]
                item['fade_in']=item['fade_out']=0
            item['words']=[{**w,'start':max(start,w['start']),'end':min(end,w['end'])} for w in old['words'] if max(start,w['start'])<min(end,w['end'])]

    @heavy
    def publish(self,args):
        def apply(db):
            draft,spec,manifest=self.read(args,db)
            if manifest['nativeHash']!=args['expectedHash'] or self.integrity(manifest):raise ValueError('MANUAL_CHANGE_DETECTED')
            target=Path(args['directory']).expanduser().resolve();guard_directory(target.parent)
            if target.exists():raise ValueError('INSTALL_TARGET_EXISTS: choose a new directory')
            if target.is_relative_to(self.store.root):raise ValueError('cannot install inside managed data root')
            source=Path(manifest['path']);target.parent.mkdir(parents=True,exist_ok=True)
            staging=target.parent/('.d-install-'+uid());staging.mkdir(exist_ok=False)
            for relative in manifest['files']:
                p=source/relative
                if relative.startswith('frames-') or relative.startswith('raster/'):continue
                q=staging/relative;q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q);checked_file(q,manifest['files'][relative])
            # Relocate every archived absolute path in native JSON and the D sidecar.
            def relocate(value):
                if isinstance(value,dict):return {k:relocate(v) for k,v in value.items()}
                if isinstance(value,list):return [relocate(v) for v in value]
                if isinstance(value,str):
                    # Native text content embeds a second JSON document, including font paths.
                    if value.startswith(('{','[')):
                        try:return canonical(relocate(json.loads(value)))
                        except json.JSONDecodeError:pass
                    return value.replace(str(source),str(target)).replace(source.as_posix(),target.as_posix())
                return value
            for name in ('draft_content.json','draft_meta_info.json','d-project.json','native-input.json'):
                path=staging/name
                if path.exists():path.write_text(canonical(relocate(json.loads(path.read_text(encoding='utf8')))),encoding='utf8')
            installed={**manifest,'path':str(target),'nativeHash':sha(staging/'draft_content.json'),'documentHash':fingerprint(json.loads((staging/'d-project.json').read_text(encoding='utf8'))),'files':{p.relative_to(staging).as_posix():sha(p) for p in staging.rglob('*') if p.is_file()}}
            (staging/'d-manifest.json').write_text(canonical(installed),encoding='utf8')
            if target.exists():raise ValueError('INSTALL_TARGET_EXISTS: destination appeared during copy')
            os.rename(staging,target)
            iid=uid();db.execute('INSERT INTO draft_installations VALUES(?,?,?,?,?)',(iid,draft['id'],manifest['revision'],str(target),canonical(installed)))
            return dict(installationId=iid,path=str(target),nativeHash=installed['nativeHash'],revision=manifest['revision'],editorUIVerified=False)
        return self.mutate('jianying_publish',args,apply)

    @heavy
    def import_draft(self,args):
        def apply(db):
            source=guard_directory(args['directory']);path=source/'draft_content.json';checked_file(path,args['expectedHash'])
            try:native=json.loads(path.read_text(encoding='utf8'))
            except (UnicodeError,json.JSONDecodeError):raise ValueError('ENCRYPTED_OR_UNREADABLE_DRAFT: no decryption or guessed conversion')
            if (source/'d-manifest.json').is_file():
                manifest=json.loads((source/'d-manifest.json').read_text(encoding='utf8'))
                if manifest['nativeHash']!=sha(path):raise ValueError('MANUAL_CHANGE_DETECTED: native edits need explicit supported import mapping')
                spec=json.loads(checked_file(source/'d-project.json',manifest['files']['d-project.json']).read_text(encoding='utf8'))
                return self.new(db,args['name'],spec,manifest['allowBaked'],dict(importedFrom=str(source),sha256=sha(path)))
            from .native_import import decode
            spec=decode(native,source,args.get('assetLicenses',{}))
            return self.new(db,args['name'],spec,False,dict(importedFrom=str(source),sha256=sha(path)))
        return self.mutate('jianying_import',args,apply)

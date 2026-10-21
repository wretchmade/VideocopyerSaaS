"""D Project 1: frame intervals are integer, half-open and program-relative."""
from __future__ import annotations
from copy import deepcopy
from fractions import Fraction
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Rate(Record):
    num: int = Field(default=30, ge=1, le=120000)
    den: int = Field(default=1, ge=1, le=10000)

    @model_validator(mode='after')
    def valid(self):
        if not 1 <= self.num / self.den <= 60: raise ValueError('fps must be 1..60')
        return self

    def seconds(self, frame): return float(Fraction(frame * self.den, self.num))


class Asset(Record):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    kind: Literal['image', 'video', 'audio', 'font', 'transcript']
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    license: str = Field(min_length=1)
    source: str = Field(min_length=1)


class Key(Record):
    frame: int = Field(ge=0)
    value: float
    easing: Literal['linear', 'hold', 'smooth'] = 'linear'


class Word(Record):
    text: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class BrandSample(Record):
    frame: int = Field(ge=0)
    visible: bool = True
    # Canvas positions of the SOURCE TL/TR/BR/BL material corners, tracked over time.
    # Never re-sort by screen position: that would discard the surface's rotation.
    quad: tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]] | None = None
    mask_asset: str | None = None


class BrandPlacement(Record):
    mode: Literal['screen', 'planar']
    target_layer: str | None = None
    occlusion: Literal['none', 'per_frame_mask'] = 'none'
    samples: list[BrandSample] = Field(default_factory=list, max_length=18000)
    # A caller's review declaration, not an automatic tracking quality score.
    reviewed: Literal[True]


class BrandLock(BrandPlacement):
    source_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    target_binding: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    mask_hashes: dict[str, str] = Field(default_factory=dict)


class BrandReference(Record):
    mode: Literal['image_to_video', 'video_edit'] = 'image_to_video'
    anchor_asset: str
    identity_assets: list[str] = Field(min_length=1, max_length=10)
    camera: Literal['locked', 'gentle', 'preserve_reference'] = 'locked'


class Layer(Record):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    kind: Literal['rect', 'image', 'video', 'text', 'component']
    component: str | None = None
    props: dict = Field(default_factory=dict)
    asset: str | None = None
    start: int = Field(default=0, ge=0)
    end: int = Field(gt=0)
    source_start: int = Field(default=0, ge=0)
    track: int = 0
    x: float = 0
    y: float = 0
    width: int = Field(default=320, ge=1, le=4096)
    height: int = Field(default=180, ge=1, le=4096)
    fit: Literal['contain', 'cover', 'stretch'] = 'contain'
    crop: tuple[int, int, int, int] | None = None
    opacity: float = Field(default=1, ge=0, le=1)
    rotation: float = 0
    scale: float = Field(default=1, gt=0, le=8)
    color: str = '#ffffff'
    keyframes: dict[str, list[Key]] = Field(default_factory=dict)
    fade_in: int = Field(default=0, ge=0)
    fade_out: int = Field(default=0, ge=0)
    text: str = Field(default='',max_length=12000)
    transcript: str | None = None
    text_align: Literal['left','center','right'] = 'left'
    vertical_align: Literal['top','middle','bottom'] = 'top'
    fonts: list[str] = Field(default_factory=list)
    font_size: int = Field(default=32, ge=1, le=512)
    line_spacing: int = Field(default=8, ge=0, le=256)
    stroke: int = Field(default=0, ge=0, le=32)
    stroke_color: str = '#000000'
    shadow: tuple[int, int] = (0, 0)
    shadow_color: str = '#00000080'
    highlight: str = '#ffff00'
    words: list[Word] = Field(default_factory=list,max_length=2000)
    brand_lock: BrandLock | None = None


class Audio(Record):
    asset: str
    start: int = Field(default=0, ge=0)
    end: int = Field(gt=0)
    source_start: int = Field(default=0, ge=0)
    volume: float = Field(default=1, ge=0, le=4)
    fade_in: int = Field(default=0, ge=0)
    fade_out: int = Field(default=0, ge=0)


class Transition(Record):
    source: str
    target: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    kind: Literal['crossfade','wipe','push'] = 'crossfade'
    direction: Literal['left','right','up','down'] = 'left'


class Action(Record):
    at: int = Field(ge=0)
    action: Literal['click', 'fill', 'scroll']
    selector: str | None = None
    text: str = ''
    y: int = 0


class Capture(Record):
    url: str = Field(pattern=r'^https?://')
    width: int = Field(default=1280, ge=16, le=4096)
    height: int = Field(default=720, ge=16, le=4096)
    frames: int = Field(default=1, ge=1, le=18000)
    fps: Rate = Field(default_factory=Rate)
    wait_selector: str | None = None
    timeout_ms: int = Field(default=30000, ge=100, le=120000)
    actions: list[Action] = Field(default_factory=list, max_length=500)
    allowed_origins: list[str] = Field(default_factory=list)


class Task(Record):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    kind: Literal['capture', 'generation', 'media', 'speech']
    depends_on: list[str] = Field(default_factory=list)
    capture: Capture | None = None
    # A declared boundary, never silently executed or treated as a free request.
    provider: str | None = None
    prompt: str | None = None
    operation: str | None = None
    inputs: list[str] = Field(default_factory=list,max_length=40)
    input_roles: list[Literal['first_frame','last_frame','reference_image','reference_video','reference_audio']] = Field(default_factory=list,max_length=40)
    options: dict = Field(default_factory=dict)
    model: str | None = None
    output_kind: Literal['image','video','audio','transcript'] = 'video'
    budget: str | None = None
    max_cost_micros: int = Field(default=0,ge=0)
    brand_reference: BrandReference | None = None


class Project(Record):
    format: Literal['d-project'] = 'd-project'
    version: Literal[1] = 1
    width: int = Field(default=640, ge=16, le=4096)
    height: int = Field(default=360, ge=16, le=4096)
    frames: int = Field(default=90, ge=1, le=108000)
    fps: Rate = Field(default_factory=Rate)
    background: str = '#000000'
    output: Literal['mp4', 'mov-alpha'] = 'mp4'
    # Preserve the review gate when a completed branded generation is imported
    # for local timing/audio assembly, without dispatching generation again.
    brand_review_required: bool = False
    assets: list[Asset] = Field(default_factory=list, max_length=500)
    layers: list[Layer] = Field(default_factory=list, max_length=500)
    audio: list[Audio] = Field(default_factory=list, max_length=100)
    tasks: list[Task] = Field(default_factory=list, max_length=100)
    transitions: list[Transition] = Field(default_factory=list,max_length=100)

    @model_validator(mode='after')
    def references(self):
        from PIL import ImageColor
        assets = {a.id: a for a in self.assets}; tasks = {t.id: t for t in self.tasks}
        for values, label in ((self.assets, 'asset'), (self.layers, 'layer'), (self.tasks, 'task')):
            if len({v.id for v in values}) != len(values): raise ValueError(f'duplicate {label} id')
        if assets.keys() & tasks.keys(): raise ValueError('task and asset IDs must be distinct')
        layers={l.id:l for l in self.layers}
        for tr in self.transitions:
            if tr.source not in layers or tr.target not in layers or tr.source==tr.target:raise ValueError('transition needs two distinct layers')
            a,b=layers[tr.source],layers[tr.target]
            if not max(a.start,b.start)<=tr.start<tr.end<=min(a.end,b.end):raise ValueError('transition must lie in both layer intervals')
            if a.fade_out or b.fade_in:raise ValueError('explicit transition cannot also fade its participating layers')
            ordered=sorted(self.layers,key=lambda l:l.track)
            if abs(ordered.index(a)-ordered.index(b))!=1:raise ValueError('transition layers must be adjacent in stacking order')
            for other in self.transitions:
                if other is not tr and {tr.source,tr.target}&{other.source,other.target} and max(tr.start,other.start)<min(tr.end,other.end):raise ValueError('overlapping transitions on one layer')
        ImageColor.getcolor(self.background, 'RGBA')
        if self.output == 'mp4' and (self.width % 2 or self.height % 2): raise ValueError('mp4 dimensions must be even')
        for layer in self.layers:
            if layer.kind=='component':
                from .components import validate
                validate(layer)
                if any(f not in assets or assets[f].kind!='font' for f in layer.fonts):raise ValueError('component font asset missing')
                media=layer.props.get('image')
                if media and media not in assets and media not in tasks:raise ValueError('component media missing')
            if not layer.start < layer.end <= self.frames: raise ValueError(f'{layer.id}: invalid frame interval')
            for value in (layer.color, layer.stroke_color, layer.shadow_color, layer.highlight): ImageColor.getcolor(value, 'RGBA')
            if layer.kind in ('image', 'video'):
                if layer.asset not in assets and layer.asset not in tasks: raise ValueError(f'{layer.id}: missing asset')
                if layer.asset in assets and assets[layer.asset].kind != layer.kind: raise ValueError('asset kind mismatch')
                if layer.asset in tasks and tasks[layer.asset].output_kind!=layer.kind:raise ValueError('task output kind mismatch')
            if layer.kind == 'text':
                if not layer.fonts or any(f not in assets or assets[f].kind != 'font' for f in layer.fonts): raise ValueError('text needs explicit font assets')
                if not layer.text and not layer.words and not layer.transcript: raise ValueError('empty text')
                if layer.transcript and layer.transcript not in assets and layer.transcript not in tasks:raise ValueError('transcript asset/task missing')
                if layer.transcript in assets and assets[layer.transcript].kind!='transcript':raise ValueError('transcript asset kind mismatch')
                if layer.transcript in tasks and tasks[layer.transcript].output_kind!='transcript':raise ValueError('transcript task kind mismatch')
                for w in layer.words:
                    if not layer.start <= w.start < w.end <= layer.end: raise ValueError('word timing outside layer')
                if any(a.end > b.start for a,b in zip(layer.words,layer.words[1:])): raise ValueError('word timing overlaps')
            if layer.crop and (min(layer.crop) < 0 or layer.crop[2] <= layer.crop[0] or layer.crop[3] <= layer.crop[1]): raise ValueError('invalid crop bounds')
            if layer.fade_in > layer.end-layer.start or layer.fade_out > layer.end-layer.start: raise ValueError('fade exceeds layer interval')
            for key, points in layer.keyframes.items():
                if key not in ('x','y','scale','rotation','opacity'): raise ValueError(f'unsupported keyframe: {key}')
                if not points or any(a.frame >= b.frame for a,b in zip(points,points[1:])): raise ValueError('keyframes must increase')
                if any(p.frame < layer.start or p.frame >= layer.end for p in points): raise ValueError('keyframe outside layer')
                if key == 'opacity' and any(not 0 <= p.value <= 1 for p in points): raise ValueError('invalid animated opacity')
                if key == 'scale' and any(not 0 < p.value <= 8 for p in points): raise ValueError('invalid animated scale')
        for a in self.audio:
            if a.asset not in assets and a.asset not in tasks: raise ValueError('missing audio asset')
            if a.asset in assets and assets[a.asset].kind not in ('audio','video'): raise ValueError('invalid audio asset')
            if a.asset in tasks and tasks[a.asset].output_kind not in ('audio','video'): raise ValueError('invalid audio task')
            if not a.start < a.end <= self.frames: raise ValueError('invalid audio interval')
        seen = set()
        while len(seen) < len(tasks):
            ready = [t for t in self.tasks if t.id not in seen and set(t.depends_on) <= seen]
            if not ready: raise ValueError('task dependency missing or cyclic')
            for t in ready:
                if any(ref not in assets and ref not in t.depends_on for ref in t.inputs):raise ValueError('task inputs must be assets or direct dependencies')
                if t.kind in ('media','speech') and not t.operation:raise ValueError('task operation required')
                if t.input_roles and len(t.inputs)!=len(t.input_roles):raise ValueError('input roles must match input count')
                if t.kind == 'capture' and not t.capture: raise ValueError('capture specification required')
                if t.capture and any(a.at >= t.capture.frames or (a.action in ('click','fill') and not a.selector) for a in t.capture.actions): raise ValueError('invalid browser action')
                seen.add(t.id)
        from .brand import validate_project
        validate_project(self)
        return self


def upgrade(value):
    """Only documented D v0 is migrated; foreign formats are never guessed."""
    value = deepcopy(value)
    if value.get('format', 'd-project') != 'd-project': raise ValueError('not a D project')
    if value.get('version') == 0:
        value['version'] = 1
        fps = value.get('fps', 30)
        if not isinstance(fps, int): raise ValueError('D v0 fps must be an integer')
        value['fps'] = dict(num=fps, den=1)
        duration = Fraction(str(value.pop('duration')))
        exact = duration * fps
        if exact.denominator != 1: raise ValueError('D v0 duration is not frame-aligned')
        value['frames'] = int(exact)
    return Project.model_validate(value)

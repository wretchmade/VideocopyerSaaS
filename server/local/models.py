from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
class Character(Strict):
    id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,50}$')
    name:str=Field(min_length=1,max_length=100)
    description:str=Field(default='',max_length=3000)
    reference_file_id:str|None=None
class Shot(Strict):
    id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,50}$')
    title:str=Field(min_length=1,max_length=100)
    description:str=Field(default='',max_length=6000)
    duration:float=Field(default=5,ge=1,le=30)
    subtitle:str=Field(default='',max_length=500)
    character_ids:list[str]=Field(default_factory=list,max_length=20)
    file_id:str|None=None
    source_start:float=Field(default=0,ge=0)
    generate:bool=False
    generation_attempt:str=Field(default='',max_length=100)
class Plan(Strict):
    title:str=Field(min_length=1,max_length=200)
    aspect:Literal['16:9','9:16','1:1']='16:9'
    characters:list[Character]=Field(default_factory=list,max_length=30)
    shots:list[Shot]=Field(default_factory=list,max_length=100)
    audio_file_id:str|None=None
    notes:str=Field(default='',max_length=5000)
    @model_validator(mode='after')
    def unique(self):
        for items in [self.characters,self.shots]:
            if len({x.id for x in items})!=len(items): raise ValueError('节点 ID 不能重复')
        ids={x.id for x in self.characters}
        if any(set(s.character_ids)-ids for s in self.shots): raise ValueError('镜头引用了不存在的人物')
        if sum(s.duration for s in self.shots)>600: raise ValueError('本地 v0.1 单片上限 10 分钟')
        return self

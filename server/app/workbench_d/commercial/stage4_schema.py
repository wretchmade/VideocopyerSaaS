from pydantic import Field
from .schema import Record

class Viewport(Record):
    x:float=Field(default=0,ge=-100000,le=100000)
    y:float=Field(default=0,ge=-100000,le=100000)
    zoom:float=Field(default=1,ge=.2,le=3)

class Group(Record):
    id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    title:str=Field(min_length=1,max_length=120)
    x:float=Field(default=0,ge=-100000,le=100000)
    y:float=Field(default=0,ge=-100000,le=100000)
    members:list[str]=Field(default_factory=list,max_length=600)
    collapsed:bool=False

class CanvasView(Record):
    viewport:Viewport=Field(default_factory=Viewport)
    groups:list[Group]=Field(default_factory=list,max_length=100)

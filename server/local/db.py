"""Control facts use portable SQLAlchemy tables; D execution stores stay project-local."""
import hashlib, json, threading, time, uuid
from contextlib import contextmanager
from sqlalchemy import create_engine, MetaData, Table, Column, String, Integer, Float, Text, select, event
from .config import DATA, CONFIG, OWNER

def uid(): return uuid.uuid4().hex
def dump(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
def digest(value): return hashlib.sha256(dump(value).encode()).hexdigest()

metadata = MetaData()
facts = Table('facts', metadata, Column('kind', String(32), primary_key=True), Column('id', String(128), primary_key=True), Column('owner', String(64), nullable=False), Column('project', String(64), nullable=False), Column('body', Text, nullable=False), Column('created', Float, nullable=False))
events = Table('events', metadata, Column('seq', Integer, primary_key=True, autoincrement=True), Column('project', String(64), nullable=False), Column('kind', String(128), nullable=False), Column('body', Text, nullable=False), Column('created', Float, nullable=False))
url = os_url = __import__('os').environ.get('VC_DATABASE_URL') or CONFIG.get('database_url') or 'sqlite:///' + (DATA/'control.sqlite3').as_posix()
engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout':30} if url.startswith('sqlite') else {}, pool_pre_ping=True)
if url.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def pragmas(conn, _): conn.execute('PRAGMA journal_mode=WAL'); conn.execute('PRAGMA foreign_keys=ON')
metadata.create_all(engine)
lock = threading.RLock()

@contextmanager
def transaction():
    with lock, engine.connect() as conn:
        try:
            if engine.dialect.name=='sqlite':conn.exec_driver_sql('BEGIN IMMEDIATE')
            elif engine.dialect.name=='postgresql':conn.exec_driver_sql('SELECT pg_advisory_xact_lock(8765001)')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback();raise

def get(c, kind, id, project=None):
    row = c.execute(select(facts.c.body).where(facts.c.kind==kind, facts.c.id==id, facts.c.owner==OWNER)).first()
    if not row: raise ValueError('记录不存在')
    value=json.loads(row[0])
    if project is not None and value.get('project') != project: raise ValueError('记录不属于此项目')
    return value

def all(c, kind, project=None):
    q=select(facts.c.body).where(facts.c.kind==kind, facts.c.owner==OWNER)
    if project is not None: q=q.where(facts.c.project==project)
    return [json.loads(r[0]) for r in c.execute(q.order_by(facts.c.created))]

def put(c, kind, id, body, project='', update=False):
    if update: c.execute(facts.update().where(facts.c.kind==kind, facts.c.id==id, facts.c.owner==OWNER).values(body=dump(body)))
    else: c.execute(facts.insert().values(kind=kind,id=id,owner=OWNER,project=project,body=dump(body),created=time.time()))
    return body

def emit(c, project, kind, body):
    return c.execute(events.insert().values(project=project,kind=kind,body=dump(body),created=time.time())).inserted_primary_key[0]

def once(c, command, payload, action):
    if not command or len(command)>100: raise ValueError('需要有效的幂等命令 ID')
    try: prior=get(c,'command',command)
    except ValueError: prior=None
    if prior:
        if prior['hash'] != digest(payload): raise ValueError('同一命令 ID 的参数发生变化')
        return prior['result']
    result=action()
    put(c,'command',command,{'hash':digest(payload),'result':result})
    return result

def reserve(c, request, project, micros, category, payload):
    if micros<=0: raise ValueError('需要已核实的正数费用上限')
    try:
        prior=get(c,'usage',request)
        if prior['hash']!=digest(payload): raise ValueError('请求参数不一致')
        return prior
    except ValueError as exc:
        if str(exc)!='记录不存在': raise
    used=sum(x['reserved_micros'] for x in all(c,'usage') if x['state']!='released')
    cap=int(CONFIG.get('test_budget_cny',0)*1000000)
    if used+micros>cap: raise ValueError('测试总预算不足；需调整范围或明确追加授权')
    return put(c,'usage',request,{'id':request,'project':project,'category':category,'reserved_micros':micros,'actual_micros':None,'state':'reserved','hash':digest(payload),'currency':'CNY'},project)

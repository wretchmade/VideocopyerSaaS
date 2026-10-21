"""Transactional revisions, command receipts and recoverable execution leases."""
from contextlib import contextmanager
import hashlib, json, os, sqlite3, time, uuid
from pathlib import Path


def canonical(value): return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def fingerprint(value): return hashlib.sha256(canonical(value).encode()).hexdigest()
def uid(): return uuid.uuid4().hex


class Connection(sqlite3.Connection):
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()


class Store:
    def __init__(self, root=None):
        self.root=Path(root or os.environ.get('D_CORE_DATA') or os.environ.get('WORKBENCH_D_DATA_DIR','data/workbench-d')).resolve()/'core'
        self.root.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT,revision INTEGER);
            CREATE TABLE IF NOT EXISTS revisions(project TEXT,revision INTEGER,document TEXT,hash TEXT,PRIMARY KEY(project,revision));
            CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY,payload TEXT,response TEXT);
            CREATE TABLE IF NOT EXISTS builds(id TEXT PRIMARY KEY,project TEXT,revision INTEGER,spec TEXT,identity TEXT,
                fingerprint TEXT UNIQUE,status TEXT,owner TEXT,lease REAL DEFAULT 0,cancel INTEGER DEFAULT 0,
                progress TEXT DEFAULT '{}',result TEXT,error TEXT,attempt INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS nodes(build TEXT,id TEXT,status TEXT,result TEXT,PRIMARY KEY(build,id));
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,build TEXT,at REAL,kind TEXT,data TEXT);
            CREATE TABLE IF NOT EXISTS brand_reviews(build TEXT PRIMARY KEY,sha256 TEXT,approved INTEGER,note TEXT);
            CREATE TABLE IF NOT EXISTS render_plans(build TEXT PRIMARY KEY,document TEXT);
            ''')

    def connect(self):
        db=sqlite3.connect(self.root/'state.sqlite',timeout=30,factory=Connection)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA synchronous=FULL')
        return db

    @contextmanager
    def transaction(self):
        db=self.connect()
        try:
            db.execute('BEGIN IMMEDIATE');yield db;db.commit()
        except BaseException: db.rollback();raise
        finally: db.close()

    def mutate(self, command_id, payload, operation):
        if not isinstance(command_id,str) or not 1 <= len(command_id)<=200: raise ValueError('commandId required (1..200 characters)')
        hashed=fingerprint(payload)
        with self.transaction() as db:
            receipt=db.execute('SELECT * FROM receipts WHERE id=?',(command_id,)).fetchone()
            if receipt:
                if receipt['payload']!=hashed: raise ValueError('IDEMPOTENCY_CONFLICT: commandId was used with a different payload')
                return json.loads(receipt['response'])
            response=operation(db)
            db.execute('INSERT INTO receipts VALUES(?,?,?)',(command_id,hashed,canonical(response)))
            return response

    def project(self, project_id, revision=None, db=None):
        if db is None:
            with self.connect() as conn: return self.project(project_id,revision,conn)
        row=db.execute('SELECT * FROM projects WHERE id=?',(project_id,)).fetchone()
        if not row: raise ValueError('project not found')
        rev=row['revision'] if revision is None else revision
        value=db.execute('SELECT * FROM revisions WHERE project=? AND revision=?',(project_id,rev)).fetchone()
        if not value: raise ValueError('revision not found')
        return dict(projectId=project_id,name=row['name'],authorRevision=rev,document=json.loads(value['document']),sha256=value['hash'])

    def build(self, build_id, db=None):
        if db is None:
            with self.connect() as conn: return self.build(build_id,conn)
        row=db.execute('SELECT * FROM builds WHERE id=?',(build_id,)).fetchone()
        if not row: raise ValueError('build not found')
        value=dict(row)
        for key in ('spec','identity','progress','result'): value[key]=json.loads(value[key]) if value[key] else None
        value['nodes']=[{**dict(n),'result':json.loads(n['result']) if n['result'] else None} for n in db.execute('SELECT * FROM nodes WHERE build=?',(build_id,))]
        return value

    def event(self,db,build,kind,data):
        db.execute('INSERT INTO events(build,at,kind,data) VALUES(?,?,?,?)',(build,time.time(),kind,canonical(data)))

    def claim(self,build_id):
        token=uid()
        with self.transaction() as db:
            build=self.build(build_id,db)
            if build['status'] in ('succeeded','failed','cancelled'): return None
            if build['owner'] and build['lease']>time.time(): return None
            if build['cancel']:
                db.execute("UPDATE builds SET status='cancelled',owner=NULL WHERE id=?",(build_id,));return None
            db.execute("UPDATE builds SET status='running',owner=?,lease=?,attempt=attempt+1 WHERE id=?",(token,time.time()+10,build_id))
            self.event(db,build_id,'claimed',dict(owner=token,pid=os.getpid(),recovered=bool(build['owner'])))
        return token

    def heartbeat(self,build_id,token):
        with self.transaction() as db:
            row=self.build(build_id,db)
            if row['owner']!=token or row['cancel'] or row['status']!='running': return False
            db.execute('UPDATE builds SET lease=? WHERE id=?',(time.time()+10,build_id));return True

    def update(self,build_id,token,**values):
        if not set(values)<={'status','progress','result','error','owner','lease'}: raise ValueError('invalid update')
        with self.transaction() as db:
            row=self.build(build_id,db)
            if row['owner']!=token: raise RuntimeError('execution lease lost')
            if row['cancel'] and values.get('status')=='succeeded': raise InterruptedError('cancel requested')
            values={k:canonical(v) if k in ('progress','result') else v for k,v in values.items()}
            db.execute('UPDATE builds SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),build_id))
            self.event(db,build_id,'update',values)

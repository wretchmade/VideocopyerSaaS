"""Durable admission and remote dispatch fencing. Integer micro-currency only."""
import json,time
from .store import canonical,fingerprint


class Ledger:
    def __init__(self,store):
        self.store=store
        with store.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS budgets(id TEXT PRIMARY KEY,project TEXT,revision INTEGER,account TEXT,currency TEXT,cap INTEGER,concurrency INTEGER);
            CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,build TEXT,task TEXT,budget TEXT,payload TEXT,cost INTEGER,state TEXT,remote TEXT,response TEXT,error TEXT);
            ''')

    def authorize(self,args):
        def apply(db):
            p=self.store.project(args['projectId'],args['revision'],db)
            cap=args['limitMicros'];concurrency=args['concurrency']
            if type(cap)!=int or cap<0 or type(concurrency)!=int or not 1<=concurrency<=100:raise ValueError('invalid budget limit/concurrency')
            if not args['account'] or not args['currency'].isalpha() or len(args['currency'])!=3:raise ValueError('account and ISO currency required')
            bid=fingerprint({'budget':args})[:32]
            db.execute('INSERT INTO budgets VALUES(?,?,?,?,?,?,?)',(bid,p['projectId'],p['authorRevision'],args['account'],args['currency'].upper(),cap,concurrency))
            return dict(budgetId=bid,**{k:v for k,v in args.items() if k!='commandId'})
        return self.store.mutate(args['commandId'],{'op':'authorize_budget',**args},apply)

    def reserve(self,build,task,account,payload,currency):
        rid=fingerprint({'build':build['id'],'task':task['id']})
        digest=fingerprint(payload)
        with self.store.transaction() as db:
            prior=db.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone()
            if prior:
                if prior['payload']!=digest:raise ValueError('remote request payload changed')
                return dict(prior)
            budget=db.execute('SELECT * FROM budgets WHERE id=?',(task['budget'],)).fetchone() if task.get('budget') else db.execute('SELECT * FROM budgets WHERE project=? AND revision=? AND account=? AND currency=? ORDER BY rowid DESC LIMIT 1',(build['project'],build['revision'],account,currency)).fetchone()
            if not budget or (budget['project'],budget['revision'],budget['account'],budget['currency'])!=(build['project'],build['revision'],account,currency):raise ValueError('explicit matching project/revision/account/currency budget required')
            cost=task['max_cost_micros']
            if cost<=0:raise ValueError('positive maximum cost required; zero does not authorize paid execution')
            used=db.execute("SELECT COALESCE(SUM(cost),0) FROM requests WHERE budget=? AND state NOT IN ('released')",(budget['id'],)).fetchone()[0]
            active=db.execute("SELECT COUNT(*) FROM requests WHERE budget=? AND state NOT IN ('succeeded','failed','released','cancelled')",(budget['id'],)).fetchone()[0]
            if used+cost>budget['cap']:raise ValueError('budget exhausted')
            if active>=budget['concurrency']:raise ValueError('budget concurrency exhausted')
            db.execute("INSERT INTO requests VALUES(?,?,?,?,?,?,'prepared',NULL,NULL,NULL)",(rid,build['id'],task['id'],budget['id'],digest,cost))
            return dict(db.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone())

    def lookup(self,build,task,payload):
        rid=fingerprint({'build':build['id'],'task':task['id']})
        with self.store.connect() as db:
            row=db.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone()
            if row and row['payload']!=fingerprint(payload):raise ValueError('remote request payload changed')
            return dict(row) if row else None

    def claim_dispatch(self,rid):
        # Commit before ANY bytes are sent; a crash from this point is unknown.
        with self.store.transaction() as db:
            from .flow import dispatch_allowed,guard
            with guard(self.store) as fence:
                request=db.execute('SELECT build FROM requests WHERE id=?',(rid,)).fetchone()
                if not request or not dispatch_allowed(self.store,db,request['build'],fence):
                    return False
                changed=db.execute("UPDATE requests SET state='submitting' WHERE id=? AND state='prepared'",(rid,)).rowcount
                # Persist the claim before releasing the stop fence.
                db.commit()
                return bool(changed)

    def update(self,rid,state,remote=None,response=None,error=None):
        with self.store.transaction() as db:
            db.execute('UPDATE requests SET state=?,remote=COALESCE(?,remote),response=COALESCE(?,response),error=? WHERE id=?',(state,remote,canonical(response) if response is not None else None,error,rid))

    def inspect(self,build):
        with self.store.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM requests WHERE build=?',(build,))]

    def budgets(self,project,revision):
        with self.store.connect() as db:
            rows=[]
            for budget in db.execute('SELECT * FROM budgets WHERE project=? AND revision=?',(project,revision)):
                used=db.execute("SELECT COALESCE(SUM(cost),0) FROM requests WHERE budget=? AND state!='released'",(budget['id'],)).fetchone()[0]
                rows.append({**dict(budget),'reservedOrSpentMicros':used,'remainingMicros':max(0,budget['cap']-used)})
            return rows

    def reconcile(self,args):
        # Attaching a provider-confirmed identity never dispatches a second POST.
        def apply(db):
            row=db.execute('SELECT * FROM requests WHERE id=?',(args['requestId'],)).fetchone()
            if not row or row['state'] not in ('submitting','unknown'):raise ValueError('only ambiguous submissions may be reconciled')
            if not args['remoteId'].strip():raise ValueError('provider-confirmed remoteId required')
            db.execute("UPDATE requests SET remote=?,state='accepted',error=NULL WHERE id=?",(args['remoteId'],args['requestId']))
            return dict(requestId=args['requestId'],state='accepted',remoteId=args['remoteId'])
        return self.store.mutate(args['commandId'],{'op':'reconcile_request',**args},apply)

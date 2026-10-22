"""Project-scoped tools and user answers shared by both Agent runtimes."""
import asyncio
from . import db, projects, commands
from .tool_registry import canonical_name, validate_arguments


class AgentTools:
    async def invoke(self,name,args,call_id):
        name=canonical_name(name)
        validate_arguments(name,args)
        if name=='get_project':
            from .bridge import public_snapshot
            return public_snapshot(self.pid)
        if name=='save_plan':return projects.save_plan(self.pid,args['base_revision'],args['plan'],'tool-'+db.digest({'project':self.pid,'call':call_id})[:40])
        if name=='ask_user':return await self.question(call_id,args['question'])
        if name=='request_local_access':
            return await self.question(call_id,('允许此项目导入目录：' if args['purpose']=='import_draft' else '允许安装到这个新的剪映目录：')+args['path']+'？输入“允许”确认。',access=args)
        if name=='request_workspace_import':
            return await self.question(call_id,'允许从已配置的本机旧 D 数据库导入工作区 '+args['workspace_id']+' 的修订 '+str(args['expected_revision'])+'？输入“允许”确认。',access={'purpose':'workspace_import',**args})
        if name=='inspect_media':
            from .media_access import inspect_media
            return await asyncio.to_thread(inspect_media,self.pid,args)
        if name=='stop_production':
            result=await asyncio.to_thread(commands.stop,self.pid)
            # Let this tool return its stop receipt before the current turn completes.
            return result
        return await asyncio.to_thread(commands.dispatch,self.pid,name,args)
    async def question(self,ident,question,access=None):
        qid=db.uid();f=asyncio.get_running_loop().create_future();self.requests[qid]=f
        with db.transaction() as c:
            db.put(c,'question',qid,{'id':qid,'project':self.pid,'question':question,'status':'pending',**({'access':access} if access else {})},self.pid)
            db.emit(c,self.pid,'question',{'id':qid,'question':question})
        try:return await f
        finally:
            self.requests.pop(qid,None)
            with db.transaction() as c:
                row=db.get(c,'question',qid,self.pid)
                if row['status']=='pending':
                    row['status']='cancelled';db.put(c,'question',qid,row,self.pid,True)
                    db.emit(c,self.pid,'question/resolved',{'id':qid,'status':'cancelled'})

    @property
    def busy(self):
        return bool(self.active or self.turn_lock.locked())

    async def answer(self,qid,answer):
        with db.transaction() as c:
            q=db.get(c,'question',qid,self.pid)
            if q['status']!='pending':return q
            future=self.requests.get(qid)
            if not future or future.done():raise ValueError('提问会话已中断，请在对话中发送答案并继续')
            if q.get('access') and answer.strip() in {'允许','确认','yes'}:
                access=q['access']
                if access['purpose']=='workspace_import':
                    q['grant']=commands.grant_workspace(c,self.pid,access['workspace_id'],access['expected_revision'],'access-'+qid)
                else:q['grant']=commands.grant_local(c,self.pid,access['path'],access['purpose'],'access-'+qid)
            q.update(status='answered',answer=answer)
            db.put(c,'question',qid,q,self.pid,True)
            projects.message(c,self.pid,'user',answer)
            db.emit(c,self.pid,'question/resolved',{'id':qid,'status':'answered'})
        future.set_result({'answer':answer,**({'grant':q['grant']} if q.get('grant') else {})})
        return q

    def cancel_questions(self):
        for qid,future in list(self.requests.items()):
            if not future.done():future.set_result({'answer':'用户停止了当前运行'})
            with db.transaction() as c:
                q=db.get(c,'question',qid,self.pid)
                if q['status']!='pending':continue
                q['status']='cancelled';db.put(c,'question',qid,q,self.pid,True)
                db.emit(c,self.pid,'question/resolved',{'id':qid,'status':'cancelled'})

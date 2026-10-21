"""Content-addressed COS copies; credentials remain in the service process."""
import hashlib, os
from pathlib import Path
from . import db
from .config import contained
from .credentials import cos_values

def client():
    from qcloud_cos import CosConfig,CosS3Client
    v=cos_values()
    if not all(v.get(k) for k in ['REGION','BUCKET','SECRET_ID','SECRET_KEY']):raise ValueError('COS 配置不完整')
    return CosS3Client(CosConfig(Region=v['REGION'],SecretId=v['SECRET_ID'],SecretKey=v['SECRET_KEY'],Scheme='https')),v

def publish(pid,fid):
    with db.transaction() as c:
        file=db.get(c,'file',fid,pid)
        if file.get('cos_verified'):return {k:v for k,v in file.items() if k not in ['path','cos_key']}
        request='cos-'+pid+'-'+file['sha256']
        # Reserve CNY 1 for the bounded <=100MB transfer and short acceptance period.
        # Account storage invoices remain external facts, not assumed zero-cost.
        db.reserve(c,request,pid,1000000,'storage',{'sha256':file['sha256'],'bytes':file['size']})
    path=contained(file['path'])
    if hashlib.sha256(path.read_bytes()).hexdigest()!=file['sha256']:raise ValueError('素材完整性检查失败')
    remote,values=client();key=values.get('PREFIX','').strip('/')+'/videocopyer-local/'+pid+'/'+file['sha256']+path.suffix
    try:
        with path.open('rb') as stream:remote.put_object(Bucket=values['BUCKET'],Key=key,Body=stream,Metadata={'sha256':file['sha256']})
        head=remote.head_object(Bucket=values['BUCKET'],Key=key)
        if int(head['Content-Length'])!=file['size']:raise ValueError('COS 对象长度校验失败')
    except Exception:
        with db.transaction() as c:
            row=db.get(c,'usage',request);row['state']='reconciling';db.put(c,'usage',request,row,pid,True)
        raise ValueError('COS 写入或校验失败，状态待核对；密钥及签名地址未输出')
    with db.transaction() as c:
        file=db.get(c,'file',fid,pid);file.update(cos_key=key,cos_verified=True);db.put(c,'file',fid,file,pid,True)
        row=db.get(c,'usage',request);row.update(state='succeeded',bill_status='待 COS 账单对账');db.put(c,'usage',request,row,pid,True)
        db.emit(c,pid,'storage/verified',{'file_id':fid,'sha256':file['sha256']})
    return {k:v for k,v in file.items() if k not in ['path','cos_key']}

def signed_file(pid,fid):
    publish(pid,fid)
    with db.transaction() as c:file=db.get(c,'file',fid,pid)
    remote,v=client();return remote.get_presigned_url(Method='GET',Bucket=v['BUCKET'],Key=file['cos_key'],Expired=7200)

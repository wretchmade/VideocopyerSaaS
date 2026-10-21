import os, time
from .config import DATA
from .production import setup_media,tick

def main():
    lock=open(DATA/'worker.lock','a+b')
    if os.name=='nt':
        import msvcrt
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:return
    else:
        import fcntl
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:return
    try:setup_media()
    except Exception:pass # Health exposes unavailable config; local renders remain possible.
    while True:
        try:tick()
        except Exception as exc:print(type(exc).__name__,flush=True)
        time.sleep(1)

if __name__=='__main__':main()

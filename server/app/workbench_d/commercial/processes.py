"""Own child lifetimes, including Chromium descendants on Windows."""
import os,signal,time


class ProcessTree:
    def __init__(self,process):
        self.process=process;self.handle=None;self.closed=False
        from .resources import current,POLICY
        self.lease=current()
        if os.name!='nt':
            if self.lease:self.lease.register(self)
            return
        import ctypes
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_=[('PerProcessUserTimeLimit',ctypes.c_int64),('PerJobUserTimeLimit',ctypes.c_int64),('LimitFlags',w.DWORD),
                      ('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),('ActiveProcessLimit',w.DWORD),
                      ('Affinity',ctypes.c_size_t),('PriorityClass',w.DWORD),('SchedulingClass',w.DWORD)]
        class IO(ctypes.Structure):_fields_=[(name,ctypes.c_uint64) for name in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
        class Extended(ctypes.Structure):
            _fields_=[('BasicLimitInformation',Basic),('IoInfo',IO),('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateJobObjectW.restype=w.HANDLE
        kernel.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
        kernel.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
        kernel.CloseHandle.argtypes=[w.HANDLE]
        kernel.TerminateJobObject.argtypes=[w.HANDLE,w.UINT]
        kernel.QueryInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.c_void_p]
        handle=kernel.CreateJobObjectW(None,None)
        limits=Extended();limits.BasicLimitInformation.LimitFlags=0x2000 # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if self.lease:
            # All heavy descendants share the same CPU set; thread count is not the quota.
            limits.BasicLimitInformation.LimitFlags |= 0x10 | 0x200
            limits.BasicLimitInformation.Affinity=sum(1<<cpu for cpu in self.lease.cpus)
            limits.JobMemoryLimit=POLICY['memory_bytes']
        if not handle or not kernel.SetInformationJobObject(handle,9,ctypes.byref(limits),ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle,int(process._handle)):
            error=ctypes.get_last_error()
            if handle:kernel.CloseHandle(handle)
            process.kill();process.wait()
            raise OSError(error,'Cannot isolate the media process tree in a Windows Job Object')
        self.handle=handle;self.kernel=kernel
        if self.lease:self.lease.register(self)

    def stats(self):
        if not self.handle:return {}
        import ctypes
        from ctypes import wintypes as w
        class Accounting(ctypes.Structure):
            _fields_=[('user',ctypes.c_int64),('kernel',ctypes.c_int64),('period_user',ctypes.c_int64),('period_kernel',ctypes.c_int64),
                      ('faults',w.DWORD),('total',w.DWORD),('active',w.DWORD),('terminated',w.DWORD)]
        value=Accounting()
        if not self.kernel.QueryInformationJobObject(self.handle,1,ctypes.byref(value),ctypes.sizeof(value),None):
            raise OSError(ctypes.get_last_error(),'Cannot read media Job accounting')
        return {'cpu_seconds':(value.user+value.kernel)/10000000,'active':value.active}

    def terminate(self):
        if self.closed:return
        if self.handle:self.kernel.TerminateJobObject(self.handle,1)
        elif os.name!='nt':
            try:os.killpg(self.process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        elif self.process.poll() is None:self.process.kill()

    def close(self):
        if self.closed:return
        self.terminate()
        self.process.wait(timeout=10)
        stats=self.stats()
        deadline=time.monotonic()+10
        while stats.get('active',0):
            if time.monotonic()>deadline:
                raise RuntimeError('Media descendants did not exit; cannot release heavy slot')
            time.sleep(.02);stats=self.stats()
        if self.handle:
            self.kernel.CloseHandle(self.handle);self.handle=None
        self.closed=True
        if self.lease:self.lease.finished(self,stats)

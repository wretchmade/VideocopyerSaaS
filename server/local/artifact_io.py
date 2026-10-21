"""Bounded, cancellable archive writes shared by delivery entry points."""
from pathlib import Path
import zipfile

def zip_member(archive,path,name,check):
    info=zipfile.ZipInfo.from_file(path,name)
    info.compress_type=archive.compression
    with Path(path).open('rb') as source,archive.open(info,'w',force_zip64=True) as target:
        while chunk:=source.read(1024*1024):
            check();target.write(chunk)
    check()

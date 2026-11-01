#!/usr/bin/env python3
"""Moteur NFS2S3 natif Windows/Linux utilisant boto3. Aucun shell/WSL requis."""
from __future__ import annotations
import argparse, concurrent.futures, hashlib, os, sys, time
from pathlib import Path
import boto3
from botocore.config import Config
from boto3.s3.transfer import TransferConfig

def md5_file(path: Path) -> str:
    h=hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser(description="Copie non destructive d'un dossier vers S3")
    p.add_argument("--source",required=True); p.add_argument("--bucket",required=True); p.add_argument("--prefix",default="")
    p.add_argument("--endpoint",default=""); p.add_argument("--region",default="eu-west-1")
    p.add_argument("--access-key",default=""); p.add_argument("--secret-key",default="")
    p.add_argument("--workers",type=int,default=8); p.add_argument("--bandwidth",type=int,default=0,help="octets/s, 0=illimité")
    p.add_argument("--verify",choices=["checksum","size","none"],default="checksum")
    p.add_argument("--dry-run",action="store_true"); p.add_argument("--immutable",action="store_true")
    p.add_argument("--follow-links",action="store_true"); p.add_argument("--exclude",action="append",default=[])
    p.add_argument("--min-age",type=int,default=0,help="âge minimum en secondes")
    p.add_argument("--retries",type=int,default=3); p.add_argument("--log-dir",default="nfs2s3_logs")
    a=p.parse_args()
    src=Path(a.source).expanduser().resolve()
    if not src.is_dir(): p.error("Le dossier source est introuvable ou inaccessible.")
    if not a.bucket: p.error("Bucket S3 obligatoire.")
    if a.workers<1: p.error("--workers doit être supérieur à zéro.")
    session=boto3.session.Session(aws_access_key_id=a.access_key or None,aws_secret_access_key=a.secret_key or None,region_name=a.region)
    s3=session.client("s3",endpoint_url=a.endpoint or None,config=Config(retries={"max_attempts":max(1,a.retries),"mode":"standard"},s3={"addressing_style":"path"}))
    prefix=a.prefix.strip("/")
    if prefix: prefix+="/"
    logdir=Path(a.log_dir); logdir.mkdir(parents=True,exist_ok=True)
    log=(logdir/f"windows_{time.strftime('%Y%m%d_%H%M%S')}.log").open("a",encoding="utf-8")
    def emit(event,**kw):
        import json
        row={"event":event,"time":time.time(),**kw}
        line=json.dumps(row,ensure_ascii=False); print(line,flush=True); log.write(line+"\n"); log.flush()
    files=[]
    now=time.time()
    for root,dirs,names in os.walk(src,followlinks=a.follow_links):
        dirs[:]=[d for d in dirs if not (Path(root)/d).is_symlink() or a.follow_links]
        for name in names:
            f=Path(root)/name
            if f.is_symlink() and not a.follow_links: continue
            rel=f.relative_to(src).as_posix()
            if any(Path(rel).match(pattern) for pattern in a.exclude): continue
            try:
                st=f.stat()
                if a.min_age and now-st.st_mtime<a.min_age: continue
                if f.is_file(): files.append((f,rel,st.st_size))
            except OSError as e: emit("error",file=str(f),message=str(e))
    total=sum(x[2] for x in files); emit("start",files=len(files),bytes=total,dry_run=a.dry_run)
    config=TransferConfig(multipart_threshold=64*1024*1024,multipart_chunksize=16*1024*1024,max_concurrency=4,use_threads=True)
    done=0; transferred=0; errors=0; uploaded=0; skipped=0; planned=0; started=time.monotonic()
    def one(item):
        f,rel,size=item; key=prefix+rel
        digest=md5_file(f) if a.verify=="checksum" or a.immutable else ""
        try:
            head=None
            try: head=s3.head_object(Bucket=a.bucket,Key=key)
            except Exception as e:
                code=getattr(e,"response",{}).get("Error",{}).get("Code","")
                if code not in ("404","NoSuchKey","NotFound"): raise
            if head:
                same_size=head.get("ContentLength")==size
                same_hash=head.get("Metadata",{}).get("nfs2s3-md5")==digest if digest else False
                if a.verify=="size" and same_size: return ("skip",rel,size,"Taille identique")
                if a.verify=="checksum" and same_size and same_hash: return ("skip",rel,size,"Checksum identique")
                if a.immutable: return ("error",rel,size,"Objet existant différent (mode immuable)")
            if a.dry_run: return ("planned",rel,size,"Simulation")
            extra={"Metadata":{"nfs2s3-md5":digest}} if digest else {}
            s3.upload_file(str(f),a.bucket,key,ExtraArgs=extra or None,Config=config)
            if a.verify=="size":
                check=s3.head_object(Bucket=a.bucket,Key=key)
                if check.get("ContentLength")!=size: raise RuntimeError("Vérification de taille échouée")
            return ("uploaded",rel,size,"OK")
        except Exception as e: return ("error",rel,size,str(e))
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures=[pool.submit(one,x) for x in files]
        for future in concurrent.futures.as_completed(futures):
            status,rel,size,msg=future.result()
            done+=1
            if status in ("uploaded","planned"): transferred+=size
            if status=="uploaded": uploaded+=1
            elif status=="skip": skipped+=1
            elif status=="planned": planned+=1
            if status=="error": errors+=1
            elapsed=max(.001,time.monotonic()-started)
            emit("progress",status=status,file=rel,done=done,files=len(files),bytes=transferred,total_bytes=total,
                 speed=int(transferred/elapsed),errors=errors,message=msg)
    emit("finish",files=len(files),uploaded=uploaded,skipped=skipped,planned=planned,bytes=transferred,errors=errors,elapsed=round(time.monotonic()-started,2))
    log.close()
    return 1 if errors else 0
if __name__=="__main__": sys.exit(main())

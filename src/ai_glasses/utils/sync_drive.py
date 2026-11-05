"""Synchronize only this experiment's artifacts; never mutate source originals."""
import argparse
import configparser
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
import tempfile
import traceback
from ai_glasses.generation import tryon_lab as lab

def invoke(args):
    result=subprocess.run(['rclone',*args,'--retries','2','--low-level-retries','2','--tpslimit','1','--tpslimit-burst','1','--checkers','2'],text=True,capture_output=True,timeout=180)
    if result.returncode:raise RuntimeError(result.stderr[-3000:])
    return result.stdout
def sync():
    lock=open(lab.ROOT/'drive_sync.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    cfg=json.loads((lab.ROOT/'drive_folders.json').read_text());folders=cfg['folders'];c=lab.connect();lab.materialize(c);lab.export(c)
    # Reconcile only generated files that belong to known successful job IDs.
    remote={}
    for ix in (5,6,7,8):
        rid=folders[lab.FOLDERS[ix]]
        for x in json.loads(invoke(['lsjson','gdrive:','--drive-root-folder-id',rid,'--files-only'])):
            remote.setdefault(x['Name'],[]).append(ix)
    for row in c.execute("SELECT j.id,j.output,r.decision FROM jobs j LEFT JOIN reviews r ON r.job_id=j.id WHERE j.kind='tryon' AND j.status='success'"):
        name=row['id']+'.png';desired={'pass':6,'exclude':7,'hold':8}.get(row['decision'],5)
        found=remote.get(name,[])
        if len(found)>1:raise ValueError('Multiple Drive copies of generated job; inspect instead of deleting: '+name)
        if found and found[0]!=desired:
            old=folders[lab.FOLDERS[found[0]]];new=folders[lab.FOLDERS[desired]]
            # The installed rclone predates connection-string overrides. Use a short-lived private config.
            original=configparser.ConfigParser(interpolation=None);original.read(Path.home()/'.config/rclone/rclone.conf')
            temporary=configparser.ConfigParser(interpolation=None)
            for alias,rid in [('tryon_src',old),('tryon_dst',new)]:temporary[alias]=dict(original['gdrive'],root_folder_id=rid)
            with tempfile.TemporaryDirectory(dir=lab.ROOT/'work') as folder:
                path=Path(folder)/'rclone.conf'
                with open(path,'w',opener=lambda p,f:os.open(p,f,0o600)) as f:temporary.write(f)
                invoke(['moveto','tryon_src:'+name,'tryon_dst:'+name,'--drive-server-side-across-configs','--config',str(path)])
    errors=[];finished_folders=[]
    for name in [*lab.FOLDERS,'11_검수완료']:
        try:
            invoke(['copy',str(lab.ROOT/name),'gdrive:','--drive-root-folder-id',folders[name],'--checksum','--fast-list','--transfers','4','--exclude','*.tmp','--exclude','*-wal','--exclude','*-shm']);finished_folders.append(name)
        except Exception as e:errors.append(dict(folder=name,error=str(e)))
    status=dict(status='partial_failure' if errors else 'success',finished=lab.now(),finished_folders=finished_folders,errors=errors,note='Only experiment folders were synchronized. Originals outside this experiment were not changed.')
    (lab.ROOT/lab.FOLDERS[9]/'drive_sync_status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2));print(json.dumps(status),flush=True)
def main():
    p=argparse.ArgumentParser();p.add_argument('--watch',action='store_true');p.add_argument('--interval',type=int,default=180);a=p.parse_args()
    while True:
        try:
            # Upload saved images before the slower diagnostics and report refresh.
            sync()
        except Exception:
            detail=traceback.format_exc();limited='rateLimitExceeded' in detail or 'RATE_LIMIT_EXCEEDED' in detail
            error=dict(status='waiting_rate_limit' if limited else 'failed',error=detail,finished=lab.now(),retry_after_seconds=a.interval if a.watch else None,data_root=str(lab.ROOT),note='Saved files remain on the HDD. The watch service retries automatically.');(lab.ROOT/lab.FOLDERS[9]/'drive_sync_status.json').write_text(json.dumps(error,ensure_ascii=False,indent=2));print(json.dumps(error,ensure_ascii=False),flush=True)
        else:
            try:
                from ai_glasses.utils import audit_images
                audit_images.main()
                from ai_glasses.training import split_experiments
                with lab.connect() as c:
                    for mode in ('strict','joint'):(lab.ROOT/lab.FOLDERS[9]/('split_'+mode+'.json')).write_text(json.dumps(split_experiments.split(c,mode),ensure_ascii=False,indent=2))
                from ai_glasses.utils import make_report
                make_report.main()
            except Exception:
                (lab.ROOT/lab.FOLDERS[9]/'report_refresh_error.json').write_text(json.dumps(dict(error=traceback.format_exc(),finished=lab.now()),ensure_ascii=False,indent=2))
        if not a.watch:break
        time.sleep(a.interval)
if __name__=='__main__':main()

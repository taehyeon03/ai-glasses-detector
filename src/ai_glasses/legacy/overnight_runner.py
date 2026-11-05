"""Run a fixed ten-hour window on the RTX host, independent of SSH clients."""
import json
import subprocess
import sys
import time
import traceback
from ai_glasses.generation import tryon_lab as lab

BATCH='overnight_10h'
def main():
    c=lab.connect();row=c.execute('SELECT * FROM batches WHERE name=?',(BATCH,)).fetchone()
    if not row:raise ValueError('Prepare the overnight plan first')
    if row['status'] in ('stopped_by_request','completed','completed_with_failures','needs_attention'):return
    meta=json.loads(row['metadata'])
    if not row['deadline']:
        started=lab.now();deadline=(lab.dt.datetime.now(lab.dt.timezone.utc)+lab.dt.timedelta(hours=meta['hours'])).isoformat()
        c.execute("UPDATE batches SET started=?,deadline=?,status='running' WHERE name=?",(started,deadline,BATCH));c.commit()
    else:deadline=row['deadline']
    if lab.now()>=deadline:
        c.execute("UPDATE batches SET status='time_limit_reached' WHERE name=?",(BATCH,));c.commit();return
    (lab.ROOT/'STOP').unlink(missing_ok=True)
    outcome='completed'
    for attempt in range(3):
        if lab.now()>=deadline:outcome='time_limit_reached';break
        command=[sys.executable,'-m','ai_glasses.generation.tryon_lab','run','--kind','all','--batch',BATCH,'--limit','2000','--retry-failed','--deadline',deadline,'--max-attempts','3']
        result=subprocess.run(command,cwd=lab.ROOT)
        if (lab.ROOT/'STOP').exists():outcome='stopped_by_request';break
        if lab.now()>=deadline:outcome='time_limit_reached';break
        pending=c.execute("SELECT count(*) FROM jobs j JOIN batch_jobs b ON b.job_id=j.id WHERE b.batch=? AND j.status IN ('pending','interrupted','failed','blocked_dependency') AND j.attempts<3",(BATCH,)).fetchone()[0]
        if not pending:
            outcome='completed_with_failures' if c.execute("SELECT count(*) FROM jobs j JOIN batch_jobs b ON b.job_id=j.id WHERE b.batch=? AND j.status!='success'",(BATCH,)).fetchone()[0] else 'completed'
            break
        if result.returncode:print(json.dumps(dict(worker_returncode=result.returncode,attempt=attempt+1)),flush=True)
        time.sleep(15)
    else:outcome='needs_attention'
    c.execute('UPDATE batches SET status=? WHERE name=?',(outcome,BATCH));c.commit()
    from ai_glasses.utils import make_report
    make_report.main()
    print(json.dumps(dict(batch=BATCH,status=outcome,finished=lab.now()),ensure_ascii=False),flush=True)
if __name__=='__main__':
    try:main()
    except Exception:
        error=dict(stage='overnight_runner',error=traceback.format_exc(),time=lab.now());(lab.ROOT/lab.FOLDERS[9]/'overnight_runner_error.json').write_text(json.dumps(error,ensure_ascii=False,indent=2));raise

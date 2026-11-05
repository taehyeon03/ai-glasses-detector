import json
import getpass
import subprocess
from ai_glasses.generation import tryon_lab as lab
from ai_glasses.legacy.overnight_plan import semantic
c=lab.connect();name='overnight_10h'
rows=list(c.execute("SELECT j.* FROM jobs j JOIN batch_jobs b ON j.id=b.job_id WHERE b.batch=? AND j.kind='tryon'",(name,)))
result=dict(checked_at=lab.now(),tryon_queue=len(rows),unique_generation_conditions=len({semantic(json.loads(r['condition'])) for r in rows}),first56_reused=c.execute("SELECT count(*) FROM jobs j JOIN batch_jobs b ON j.id=b.job_id WHERE b.batch=? AND j.kind='tryon' AND json_extract(j.condition,'$.batch')='first_56' AND j.status!='superseded'",(name,)).fetchone()[0],user_reference_poses=[dict(id=r['id'],status=r['status'],pose=json.loads(r['condition'])['pose']) for r in c.execute("SELECT * FROM jobs WHERE kind='portrait' AND json_extract(condition,'$.person_id')='U01'")],batch=dict(c.execute('SELECT name,started,deadline,status FROM batches WHERE name=?',(name,)).fetchone()))
assert result['tryon_queue']==800
assert result['unique_generation_conditions']==800
assert result['first56_reused']==56
services={}
for unit in ('tryon-overnight.service','tryon-review.service','tryon-drive-sync.service'):
    info=subprocess.check_output(['systemctl','--user','show',unit,'-p','ActiveState','-p','SubState','-p','MainPID','-p','ControlGroup','-p','UnitFileState'],text=True)
    services[unit]=dict(line.split('=',1) for line in info.strip().splitlines());assert services[unit]['ActiveState']=='active'
result['services']=services
result['lingering']=subprocess.check_output(['loginctl','show-user',getpass.getuser(),'-p','Linger'],text=True).strip()
result['ac_sleep_policy']=subprocess.check_output(['gsettings','get','org.gnome.settings-daemon.plugins.power','sleep-inactive-ac-type'],text=True).strip()
assert result['lingering']=='Linger=yes'
assert result['ac_sleep_policy']=="'nothing'"
(lab.ROOT/lab.FOLDERS[9]/'automation_verified.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False))

"""Migrate queued jobs and record the configured background and lighting choices."""
import collections
import json
import sqlite3
from ai_glasses.generation import face_framing as framing
from ai_glasses.generation import tryon_lab as lab

def main():
    c=lab.connect()
    backup=lab.ROOT/'work'/('before_scene_policy_'+lab.now().replace(':','-')+'.sqlite')
    with sqlite3.connect(backup) as destination:c.backup(destination)
    changes=framing.migrate_pending(c)
    rows=c.execute("SELECT condition FROM jobs WHERE kind IN ('portrait','tryon') AND (status IN ('pending','interrupted','blocked_dependency','waiting_reference') OR (status='failed' AND attempts<3))").fetchall()
    conditions=[json.loads(row[0]) for row in rows]
    report=dict(created=lab.now(),scene_version=framing.SCENE_VERSION,configured_jobs=sum(x.get('scene_policy_version')==framing.SCENE_VERSION for x in conditions),changes_this_pass=changes,backgrounds=dict(collections.Counter(x.get('background_style','missing') for x in conditions)),lighting=dict(collections.Counter(x.get('lighting_variant','missing') for x in conditions)),pending_without_policy=sum(bool(x.get('prompt')) and x.get('scene_policy_version')!=framing.SCENE_VERSION for x in conditions),backup=str(backup))
    (lab.ROOT/lab.FOLDERS[9]/'scene_policy_20261103.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    lab.export(c)
    print(json.dumps({k:v for k,v in report.items() if k not in ('changes_this_pass','backup')},ensure_ascii=False))

if __name__=='__main__':main()

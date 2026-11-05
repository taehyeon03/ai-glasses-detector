import json
from ai_glasses.review import public_review_store as store
from ai_glasses.generation import tryon_lab as lab
c=lab.connect();store.init(c)
for r in c.execute('SELECT child_job FROM regeneration_requests'):c.execute('INSERT OR IGNORE INTO batch_jobs VALUES(?,?,?)',('public_regeneration',r[0],0))
c.commit();lab.run(c,'all',1,True,'public_regeneration',max_attempts=3);store.reconcile(c)
print(json.dumps(store.request_rows(c),ensure_ascii=False))

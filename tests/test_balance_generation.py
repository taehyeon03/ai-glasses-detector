import json,tempfile,unittest
from pathlib import Path
from PIL import Image
from ai_glasses.generation import tryon_lab as lab
from ai_glasses.review import public_review_store as store
from ai_glasses.generation import balance_generation as balance

class BalanceTests(unittest.TestCase):
 def setUp(self):
  self.old=lab.ROOT;self.temp=tempfile.TemporaryDirectory();lab.ROOT=Path(self.temp.name);self.c=lab.connect();store.init(self.c)
  for pose in balance.POSES:
   path=lab.ROOT/(pose+'.png');Image.new('RGB',(64,64),'white').save(path)
   self.c.execute('INSERT INTO jobs(id,kind,condition,status,output,output_sha256) VALUES(?,?,?,?,?,?)',('P_'+pose,'portrait',json.dumps(dict(person_id='K01',pose=pose,hair='short',face_origin='fictional_generated')),'success',str(path),lab.digest(path)))
  for key,category in [('A1','A'),('A2','A'),('B','B'),('C','C'),('EXCLUDED','A')]:
   path=lab.ROOT/(key+'.png');Image.new('RGB',(64,64),'black').save(path)
   self.c.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)',(key,str(path),lab.digest(path),key,category,'present' if category=='A' else 'absent','evidence',json.dumps(dict(selected=key!='EXCLUDED',generation_excluded=key=='EXCLUDED'))))
  self.c.commit();self.config=dict(enabled=True,target_per_category=6,reserve_multiplier=1.25)
 def tearDown(self):self.c.close();lab.ROOT=self.old;self.temp.cleanup()
 def job(self,key,source,status='success',decision=None,parent='P_front'):
  con=dict(kind='tryon',source_id=source,portrait_job=parent,person_id='K01',pose='front',prompt='wear',seed=len(key))
  path=lab.ROOT/lab.FOLDERS[5]/(key+'.png');Image.new('RGB',(64,64),'green').save(path)
  self.c.execute('INSERT INTO jobs(id,kind,condition,status,output,output_sha256) VALUES(?,?,?,?,?,?)',(key,'tryon',json.dumps(con),status,str(path),lab.digest(path)))
  if decision:self.c.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?)',(key,decision,'human text','[]','human',lab.now()))
  self.c.commit()
 def test_balanced_targets_surplus_existing_queue_and_idempotence(self):
  for i in range(4):self.job('approved'+str(i),'A1',decision='pass')
  for i in range(3):self.job('unreviewed'+str(i),'C')
  self.job('existing_queue','B','pending')
  before=[tuple(r) for r in self.c.execute('SELECT * FROM reviews')]
  report=balance.reconcile(self.c,self.config)
  for cat in ('A','B','C'):self.assertEqual(sum(x['quota'] for x in report['products'] if x['category']==cat),6)
  self.assertEqual(report['category_priority'][0],'B');self.assertNotIn('EXCLUDED',[x['product'] for x in report['products']])
  self.assertEqual(next(x for x in report['products'] if x['product']=='A1')['new_jobs'],0)
  self.assertEqual(next(x for x in report['products'] if x['product']=='B')['reused_pending'],1)
  self.assertEqual(next(x for x in report['products'] if x['product']=='C')['new_jobs'],10)
  self.assertEqual(balance.reconcile(self.c,self.config)['created_this_pass'],0)
  self.assertEqual(before,[tuple(r) for r in self.c.execute('SELECT * FROM reviews')])
  selected=json.loads((lab.ROOT/lab.FOLDERS[9]/'balanced_approved_candidates.json').read_text());self.assertEqual(selected['counts']['A'],3)
 def test_scheduler_skips_impossible_batch_and_reaches_overnight_jobs(self):
  self.job('blocked','A1','blocked_dependency',parent='superseded_missing')
  self.job('ready','B','pending')
  self.c.execute('INSERT INTO batch_jobs VALUES(?,?,?)',('diversity_20261102_v1','blocked',0))
  self.c.execute('INSERT INTO batch_jobs VALUES(?,?,?)',('overnight_10h','ready',0));self.c.commit()
  self.assertEqual(balance.next_batch(self.c),'overnight_10h')
 def test_new_jobs_keep_latest_product_and_face_policies(self):
  balance.reconcile(self.c,self.config)
  row=self.c.execute("SELECT condition FROM jobs WHERE json_extract(condition,'$.batch')=? LIMIT 1",(balance.BATCH,)).fetchone();con=json.loads(row[0])
  self.assertEqual(con['foreground_fraction_target'],.9);self.assertIn('hinge_fidelity_version',con);self.assertIn('background_style',con)
  self.assertIn(con['portrait_job'],{row['id'] for row in self.c.execute("SELECT id FROM jobs WHERE kind='portrait' AND status='success'")})
 def test_pilot_stops_without_falling_back_to_large_or_legacy_batches(self):
  self.job('pilot','C','pending');self.job('legacy','B','pending')
  self.c.execute('INSERT INTO batch_jobs VALUES(?,?,?)',('small_pilot','pilot',0));self.c.execute('INSERT INTO batch_jobs VALUES(?,?,?)',('overnight_10h','legacy',0));self.c.commit()
  (lab.ROOT/balance.SETTINGS).write_text(json.dumps(dict(enabled=False,mode='pilot',active_batch='small_pilot')))
  self.assertEqual(balance.next_batch(self.c),'small_pilot')
  self.c.execute("UPDATE jobs SET status='success' WHERE id='pilot'");self.c.commit();self.assertIsNone(balance.next_batch(self.c))
  self.c.execute("UPDATE jobs SET status='interrupted',attempts=3 WHERE id='pilot'");self.c.commit();self.assertIsNone(balance.next_batch(self.c))

if __name__=='__main__':unittest.main()

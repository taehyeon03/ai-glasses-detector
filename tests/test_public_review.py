import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from ai_glasses.review import public_review_store as store
from ai_glasses.generation import tryon_lab as lab
class PublicReviewTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=lab.ROOT;lab.ROOT=Path(self.tmp.name);self.c=lab.connect();store.init(self.c)
  source=lab.ROOT/'real.png';Image.new('RGB',(64,64),'white').save(source)
  self.c.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)',('S',str(source),lab.digest(source),'Test frame','A','present','https://example.org','{}'));self.c.commit()
  self.key=lab.add_job(self.c,dict(camera='present',source_id='S',portrait_job='P',prompt='original prompt',seed=1,person_id='T'),'tryon')
  self.output=lab.ROOT/lab.FOLDERS[5]/(self.key+'.png');Image.new('RGB',(64,64),'green').save(self.output)
  self.c.execute("UPDATE jobs SET status='success',output=?,output_sha256=? WHERE id=?",(str(self.output),lab.digest(self.output),self.key));self.c.commit()
  self.data=dict(reviewer='시험 전용',comment='비공개 시험',checks=['unknown']*6,decision='hold',version=0)
 def tearDown(self):self.c.close();lab.ROOT=self.old;self.tmp.cleanup()
 def test_draft_is_private_and_durable(self):
  store.draft(self.c,self.key,'sessionA',self.data);self.c.close();self.c=lab.connect()
  self.assertIsNotNone(self.c.execute('SELECT * FROM review_drafts WHERE session=?',('sessionA',)).fetchone())
  self.assertIsNone(self.c.execute('SELECT * FROM review_drafts WHERE session=?',('sessionB',)).fetchone())
  self.assertEqual(self.c.execute('SELECT count(*) FROM reviews').fetchone()[0],0)
 def test_taehyun_prioritizes_deficient_class_and_rotates_models(self):
  store.submit(self.c,self.key,'test',dict(self.data,decision='pass',mode='quick'))
  rows=[dict(id='a',category='A',product='Test frame'),dict(id='b1',category='B',product='B1'),dict(id='b2',category='B',product='B1'),dict(id='c',category='B',product='B2')]
  self.assertEqual([r['id'] for r in store.review_priority(self.c,rows,'검수자 1')],['b1','c','b2','a'])
  self.assertEqual(store.review_priority(self.c,rows,'검수자 2'),rows)
  self.assertIn('일반 안경 우선',store.priority_message(self.c,'검수자 1'))
 def test_priority_batch_preserves_claims_and_current_image(self):
  self.add_many_jobs(15)
  source=lab.ROOT/'ordinary.png';Image.new('RGB',(64,64),'white').save(source)
  self.c.execute("INSERT INTO sources SELECT 'B',?,sha256,'Ordinary frame','B','absent',evidence,metadata FROM sources WHERE id='S'",(str(source),))
  ids=[r[0] for r in self.c.execute('SELECT id FROM jobs WHERE id<>? LIMIT 5',(self.key,))]
  for key in ids:
   con=json.loads(self.c.execute('SELECT condition FROM jobs WHERE id=?',(key,)).fetchone()[0]);con['source_id']='B'
   self.c.execute('UPDATE jobs SET condition=? WHERE id=?',(json.dumps(con),key))
  self.c.commit();store.submit(self.c,self.key,'test',dict(self.data,decision='pass',mode='quick'))
  other=store.claim_batch(self.c,'other','검수자 2');store.release(self.c,other['ids'][0],'other',True)
  protected=store.claim(self.c,'other','검수자 2',preferred=ids[0])['id']
  first=store.claim_batch(self.c,'priority-reviewer','검수자 1')
  self.assertNotIn(protected,first['ids']);self.assertEqual(first['jobs'][next(i for i,r in enumerate(first['jobs']) if r['id']==first['ids'][0])]['category'],'B')
  second=store.claim_batch(self.c,'priority-reviewer','검수자 1',preferred=first['ids'][0])
  self.assertEqual(second['ids'][0],first['ids'][0]);self.assertEqual(self.c.execute('SELECT owner FROM review_claims WHERE job_id=?',(protected,)).fetchone()[0],'other')
 def test_photo_numbers_survive_reordering_archival_and_new_images(self):
  initial=store.catalog(self.c)[0]['number'];other=self.add_second_job();numbers={r['id']:r['number'] for r in store.catalog(self.c)}
  self.assertEqual(numbers[self.key],initial);self.assertNotEqual(numbers[other],initial)
  self.c.execute("UPDATE jobs SET finished='2099-01-01' WHERE id=?",(self.key,));self.c.commit()
  self.assertEqual({r['id']:r['number'] for r in store.catalog(self.c)},numbers)
  self.c.execute("UPDATE jobs SET status='quarantined_category_scope' WHERE id=?",(other,));self.c.commit()
  self.assertEqual(store.catalog(self.c)[0]['number'],initial)
  self.c.execute("UPDATE jobs SET status='success' WHERE id=?",(other,));self.c.commit()
  self.assertEqual({r['id']:r['number'] for r in store.catalog(self.c)},numbers)
 def test_last_review_is_per_person_and_uses_history_not_current_owner(self):
  other=self.add_second_job();store.submit(self.c,self.key,'ownerA',dict(self.data,reviewer='검수자 1'))
  store.submit(self.c,other,'ownerB',dict(self.data,reviewer='검수자 2'))
  store.submit(self.c,self.key,'ownerC',dict(self.data,reviewer='검수자 3',version=store.version(self.c,self.key)))
  last=store.last_reviewed(self.c);self.assertEqual(last['검수자 1']['id'],self.key);self.assertEqual(last['검수자 2']['id'],other);self.assertEqual(last['검수자 3']['id'],self.key)
  self.assertIsInstance(last['검수자 1']['number'],int)
  self.c.execute("UPDATE jobs SET status='quarantined_category_scope' WHERE id=?",(self.key,));self.c.commit()
  self.assertNotIn('검수자 1',store.last_reviewed(self.c));self.assertIn('검수자 2',store.last_reviewed(self.c))
 def test_archive_and_history_are_durable(self):
  store.submit(self.c,self.key,'A',self.data);self.c.close();self.c=lab.connect()
  self.assertTrue((lab.ROOT/store.ARCHIVE/(self.key+'.png')).is_file());self.assertFalse(self.output.exists())
  data=dict(self.data,decision='exclude',version=store.version(self.c,self.key));store.submit(self.c,self.key,'A',data)
  self.assertEqual(self.c.execute('SELECT count(*) FROM review_events').fetchone()[0],2)
 def test_concurrent_review_does_not_overwrite(self):
  def save(name):
   c=lab.connect()
   try:store.submit(c,self.key,name,self.data);return 'saved'
   except store.Conflict:return 'conflict'
   finally:c.close()
  with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(save,['A','B']))
  self.assertCountEqual(results,['saved','conflict']);self.assertEqual(self.c.execute('SELECT count(*) FROM reviews').fetchone()[0],1)
 def test_request_atomically_creates_new_job_and_preserves_original(self):
  data=dict(self.data,decision='regenerate',reason='lens',notes='Keep the dark lenses opaque')
  result=store.submit(self.c,self.key,'A',data);child=self.c.execute('SELECT * FROM jobs WHERE id=?',(result['child_job'],)).fetchone();con=json.loads(child['condition'])
  self.assertEqual(child['status'],'pending');self.assertEqual(con['regeneration_of'],self.key);self.assertIn('opaque',con['prompt']);self.assertNotEqual(child['id'],self.key)
  self.assertTrue((lab.ROOT/store.ARCHIVE/(self.key+'.png')).is_file())
  with self.assertRaises(store.Conflict):store.submit(self.c,self.key,'B',dict(data,version=store.version(self.c,self.key)))
  self.assertEqual(self.c.execute('SELECT count(*) FROM regeneration_requests').fetchone()[0],1)
 def test_request_can_change_to_a_new_student_identity(self):
  portrait=dict(person_id='K05',cohort='korean_students_v1',pose='front',hair='layered hair',light='daylight')
  parent=lab.add_job(self.c,portrait,'portrait')
  result=store.submit(self.c,self.key,'A',dict(self.data,decision='regenerate',reason='face',target_person='K05'))
  con=json.loads(self.c.execute('SELECT condition FROM jobs WHERE id=?',(result['child_job'],)).fetchone()[0])
  self.assertEqual(con['portrait_job'],parent);self.assertEqual(con['person_id'],'K05');self.assertEqual(con['cohort'],'korean_students_v1')
 def test_regeneration_uses_replacement_source_and_close_k04_reference(self):
  old=json.loads(self.c.execute('SELECT condition FROM jobs WHERE id=?',(self.key,)).fetchone()[0]);old.update(person_id='K04',product='Test frame',prompt='old geometry')
  self.c.execute('UPDATE jobs SET condition=? WHERE id=?',(json.dumps(old),self.key))
  self.c.execute('UPDATE sources SET metadata=? WHERE id=?',(json.dumps(dict(selected=False,detail_prompt='old geometry')),'S'))
  source=dict(self.c.execute('SELECT * FROM sources WHERE id="S"').fetchone());meta=dict(selected=True,detail_prompt='verified central bridge camera')
  self.c.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)',('S2',str(lab.ROOT/'replacement.png'),'replacement-sha','Test frame','A','present','official',json.dumps(meta)))
  parent=lab.add_job(self.c,dict(person_id='K04',protocol='korean_students_facecrop_v3'),'portrait')
  self.c.execute('UPDATE jobs SET status="success" WHERE id=?',(parent,));self.c.commit()
  result=store.submit(self.c,self.key,'A',dict(self.data,decision='regenerate',reason='camera'))
  con=json.loads(self.c.execute('SELECT condition FROM jobs WHERE id=?',(result['child_job'],)).fetchone()[0])
  self.assertEqual(con['source_id'],'S2');self.assertEqual(con['source_sha256'],'replacement-sha');self.assertEqual(con['portrait_job'],parent)
  self.assertIn('verified central bridge camera',con['prompt']);self.assertNotIn('old geometry',con['prompt'])
  self.assertEqual(json.loads(self.c.execute('SELECT condition FROM jobs WHERE id=?',(self.key,)).fetchone()[0])['source_id'],'S')
 def test_review_stats_count_latest_decision_once_and_preserve_retired_reviews(self):
  self.assertEqual(store.review_stats(self.c)['A']['reviewed'],0)
  store.submit(self.c,self.key,'A',self.data)
  store.submit(self.c,self.key,'A',dict(self.data,decision='exclude',version=store.version(self.c,self.key)))
  self.c.execute("UPDATE jobs SET status='superseded' WHERE id=?",(self.key,));self.c.commit()
  stats=store.review_stats(self.c)
  self.assertEqual(stats['A'],dict(reviewed=1,passed=0,excluded=1,held=0,products=1))
  self.assertEqual(stats['B']['reviewed'],0)
  self.assertEqual(self.c.execute('SELECT count(*) FROM review_events').fetchone()[0],2)
 def test_exclude_queues_child_and_preserves_excluded_decision_with_both_feedback_fields(self):
  result=store.submit(self.c,self.key,'A',dict(self.data,decision='exclude',comment='코받침이 다릅니다',notes='렌즈를 투명하게 유지'))
  con=json.loads(self.c.execute('SELECT condition FROM jobs WHERE id=?',(result['child_job'],)).fetchone()[0])
  self.assertEqual(self.c.execute('SELECT decision FROM reviews WHERE job_id=?',(self.key,)).fetchone()[0],'exclude')
  self.assertIn('코받침이 다릅니다',con['prompt']);self.assertIn('렌즈를 투명하게 유지',con['prompt'])
  self.assertEqual(store.backfill_excluded(self.c),[])
 def test_manual_regeneration_includes_comment_and_notes(self):
  result=store.submit(self.c,self.key,'A',dict(self.data,decision='regenerate',reason='camera',comment='카메라 위치를 수정',notes='오른쪽 구멍은 조명'))
  con=json.loads(self.c.execute('SELECT condition FROM jobs WHERE id=?',(result['child_job'],)).fetchone()[0])
  self.assertIn('카메라 위치를 수정',con['prompt']);self.assertIn('오른쪽 구멍은 조명',con['prompt'])
 def test_existing_excluded_backfill_keeps_all_human_decisions_and_is_idempotent(self):
  self.c.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?)',(self.key,'exclude','원본과 다름',json.dumps(['unknown']*6),'시험 전용',lab.now()));self.c.commit()
  before=[tuple(r) for r in self.c.execute('SELECT * FROM reviews')]
  created=store.backfill_excluded(self.c);self.assertEqual(len(created),1);self.assertEqual(store.backfill_excluded(self.c),[])
  self.assertEqual(before,[tuple(r) for r in self.c.execute('SELECT * FROM reviews')]);self.assertEqual(self.c.execute('SELECT count(*) FROM review_events').fetchone()[0],0)
 def test_excluding_with_existing_pending_regeneration_reuses_it(self):
  first=store.submit(self.c,self.key,'A',dict(self.data,decision='regenerate',reason='camera'))
  result=store.submit(self.c,self.key,'A',dict(self.data,decision='exclude',version=store.version(self.c,self.key)))
  self.assertEqual(result['child_job'],first['child_job']);self.assertEqual(self.c.execute('SELECT count(*) FROM regeneration_requests').fetchone()[0],1)
 def test_excluded_product_scope_prevents_new_generation(self):
  self.c.execute('UPDATE sources SET metadata=? WHERE id=?',(json.dumps(dict(generation_excluded=True,generation_excluded_reason='스포츠 선글라스 제외')),'S'));self.c.commit()
  result=store.submit(self.c,self.key,'A',dict(self.data,decision='exclude'))
  self.assertEqual(self.c.execute('SELECT status FROM jobs WHERE id=?',(result['child_job'],)).fetchone()[0],'excluded_by_scope')
 def test_camera_free_smart_reviews_are_counted_separately(self):
  self.c.execute("UPDATE sources SET category='C',camera='absent' WHERE id='S'");self.c.commit()
  store.submit(self.c,self.key,'A',dict(self.data,decision='pass',mode='quick'))
  stats=store.review_stats(self.c)
  self.assertEqual(stats['C']['reviewed'],1);self.assertEqual(stats['C']['passed'],1);self.assertEqual(stats['C']['products'],1)
  self.assertEqual(stats['A']['reviewed'],0);self.assertEqual(stats['B']['reviewed'],0)
 def test_dataset_stats_separate_usable_images_from_retired_and_unfinished_jobs(self):
  self.c.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?)',(self.key,'pass','','[]','reviewer',lab.now()))
  for key,status,attempts in [('waiting','success',0),('retired','superseded',0),('archive','quarantined_lens_tint',0),('queued','pending',0),('retry','failed',1),('stopped','failed',3),('reference','waiting_reference',0),('active','running',1)]:
   self.c.execute('INSERT INTO jobs(id,kind,condition,status,attempts) VALUES(?,?,?,?,?)',(key,'tryon',json.dumps(dict(source_id='S')),status,attempts))
  for key in ('retired','archive'):self.c.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?)',(key,'pass','','[]','reviewer',lab.now()))
  self.c.commit();stats=store.dataset_stats(self.c)
  self.assertEqual(stats['A'],dict(generated=2,passed=1,excluded=0,held=0,waiting=1,products=1,passed_products=1,queued=3,running=1))
  self.assertEqual(stats['B']['generated'],0);self.assertEqual(stats['C']['generated'],0)
  self.c.execute("UPDATE reviews SET decision='hold' WHERE job_id=?",(self.key,));self.c.commit()
  stats=store.dataset_stats(self.c)['A'];self.assertEqual(stats['passed'],0);self.assertEqual(stats['held'],1);self.assertEqual(stats['passed_products'],0)
 def test_reset_archives_only_unreviewed_bytes_and_queues_one_replacement(self):
  from ai_glasses.legacy import reset_unreviewed as reset
  reviewed=lab.add_job(self.c,dict(camera='present',source_id='S',portrait_job='P',prompt='reference',seed=2),'tryon')
  path=lab.ROOT/lab.FOLDERS[5]/(reviewed+'.png');Image.new('RGB',(64,64),'blue').save(path)
  self.c.execute("UPDATE jobs SET status='success',output=?,output_sha256=? WHERE id=?",(str(path),lab.digest(path),reviewed));self.c.commit()
  store.submit(self.c,reviewed,'review-session',dict(self.data,decision='pass',mode='quick'))
  before=[tuple(r) for r in self.c.execute('SELECT * FROM reviews')];sha=lab.digest(self.output)
  self.c.execute('INSERT INTO review_claims VALUES(?,?,?,?)',(self.key,'old-owner','reviewer',9999999999));self.c.commit()
  result=reset.reset(self.c);self.assertEqual(result['archived'],1)
  self.assertEqual(before,[tuple(r) for r in self.c.execute('SELECT * FROM reviews')]);self.assertFalse(self.output.exists())
  original=self.c.execute('SELECT * FROM jobs WHERE id=?',(self.key,)).fetchone();self.assertEqual(original['status'],reset.STATUS);self.assertEqual(lab.digest(original['output']),sha)
  child=result['items'][0]['child_job'];con=json.loads(self.c.execute('SELECT condition FROM jobs WHERE id=?',(child,)).fetchone()[0]);self.assertIn('hinge_fidelity_version',con);self.assertIn('최신',con['prompt'])
  self.assertIsNotNone(self.c.execute('SELECT 1 FROM batch_jobs WHERE batch=? AND job_id=?',(reset.BATCH,child)).fetchone())
  self.assertEqual(self.c.execute('SELECT count(*) FROM review_claims WHERE job_id=?',(self.key,)).fetchone()[0],0)
  self.assertEqual([r['id'] for r in store.catalog(self.c)],[reviewed]);self.assertEqual(store.request_rows(self.c),[]);self.assertEqual(reset.reset(self.c),result)
 def test_camera_free_category_exclusion_preserves_review_and_archive_bytes(self):
  from ai_glasses.legacy import exclude_camera_free_smart as scope
  self.c.execute("UPDATE sources SET category='C',camera='absent' WHERE id='S'");self.c.commit()
  store.submit(self.c,self.key,'review-session',dict(self.data,decision='pass',mode='quick'))
  before=[tuple(r) for r in self.c.execute('SELECT * FROM reviews')]
  result=scope.exclude(self.c);self.assertEqual(len(result['archived']),1)
  self.assertEqual(before,[tuple(r) for r in self.c.execute('SELECT * FROM reviews')])
  lab.materialize(self.c);store.reconcile(self.c)
  self.assertEqual(store.catalog(self.c),[]);self.assertEqual(store.dataset_stats(self.c)['C']['generated'],0);self.assertEqual(store.review_stats(self.c)['C']['reviewed'],0)
  self.assertFalse((lab.ROOT/store.ARCHIVE/(self.key+'.png')).exists())
  row=self.c.execute('SELECT * FROM jobs WHERE id=?',(self.key,)).fetchone();self.assertEqual(lab.digest(row['output']),row['output_sha256'])
  meta=json.loads(self.c.execute("SELECT metadata FROM sources WHERE id='S'").fetchone()[0]);self.assertTrue(meta['generation_excluded'])
  self.assertEqual(scope.exclude(self.c),result)
 def test_tinted_quarantine_preserves_bytes_reviews_and_cannot_be_resurrected(self):
  from ai_glasses.legacy import quarantine_tinted_lenses as removal
  store.submit(self.c,self.key,'A',dict(self.data,decision='pass',mode='quick'))
  before=[tuple(r) for r in self.c.execute('SELECT * FROM reviews')];oldoutput=self.c.execute('SELECT output FROM jobs WHERE id=?',(self.key,)).fetchone()[0];sha=lab.digest(oldoutput)
  result=removal.quarantine(self.c,{'Test frame'});self.assertEqual(len(result['quarantined']),1)
  self.assertFalse(Path(oldoutput).exists());row=self.c.execute('SELECT * FROM jobs WHERE id=?',(self.key,)).fetchone();self.assertEqual(row['status'],removal.STATUS);self.assertEqual(lab.digest(row['output']),sha)
  self.assertEqual(before,[tuple(r) for r in self.c.execute('SELECT * FROM reviews')]);self.assertEqual(store.review_stats(self.c)['A']['reviewed'],0);self.assertEqual(store.catalog(self.c),[])
  store.reconcile(self.c);self.assertFalse(Path(oldoutput).exists());self.assertFalse((lab.ROOT/store.ARCHIVE/(self.key+'.png')).exists())
  self.assertEqual(len(removal.quarantine(self.c,{'Test frame'})['quarantined']),0)
 def test_neutral_lens_restore_recovers_exact_files_and_human_decisions(self):
  from ai_glasses.legacy import quarantine_tinted_lenses as removal
  from ai_glasses.legacy import restore_neutral_lenses as recovery
  con=json.loads(self.c.execute('SELECT condition FROM jobs WHERE id=?',(self.key,)).fetchone()[0]);con['product']='Test frame';self.c.execute('UPDATE jobs SET condition=? WHERE id=?',(json.dumps(con),self.key));self.c.commit()
  store.submit(self.c,self.key,'A',dict(self.data,decision='pass',mode='quick'));before=[tuple(r) for r in self.c.execute('SELECT * FROM reviews')];path=self.c.execute('SELECT output FROM jobs WHERE id=?',(self.key,)).fetchone()[0];sha=lab.digest(path)
  removal.quarantine(self.c,{'Test frame'});result=recovery.restore(self.c,{'Vivid mirrored model'})
  self.assertEqual(result['restored'],[self.key]);self.assertTrue(Path(path).exists());self.assertEqual(lab.digest(path),sha);self.assertTrue((lab.ROOT/store.ARCHIVE/(self.key+'.png')).exists())
  self.assertEqual(before,[tuple(r) for r in self.c.execute('SELECT * FROM reviews')]);self.assertEqual(self.c.execute('SELECT count(*) FROM lens_quarantine').fetchone()[0],0);self.assertEqual(store.review_stats(self.c)['A']['passed'],1)
  self.assertFalse(json.loads(self.c.execute('SELECT metadata FROM sources WHERE id="S"').fetchone()[0]).get('generation_excluded',False))
  self.assertEqual(recovery.restore(self.c,{'Vivid mirrored model'})['restored'],[])
 def test_pass_requires_complete_checks(self):
  with self.assertRaises(ValueError):store.submit(self.c,self.key,'A',dict(self.data,decision='pass'))
  self.assertEqual(store.version(self.c,self.key),0)
 def test_stale_request_leaves_no_orphan_generation(self):
  store.submit(self.c,self.key,'A',self.data)
  with self.assertRaises(store.Conflict):store.submit(self.c,self.key,'B',dict(self.data,decision='regenerate',reason='camera'))
  self.assertEqual(self.c.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
 def add_second_job(self):
  con=dict(camera='present',source_id='S',portrait_job='P',prompt='test',seed=2,person_id='T')
  key=lab.add_job(self.c,con,'tryon');path=lab.ROOT/lab.FOLDERS[5]/(key+'.png');Image.new('RGB',(64,64),'blue').save(path)
  self.c.execute("UPDATE jobs SET status='success',output=?,output_sha256=? WHERE id=?",(str(path),lab.digest(path),key));self.c.commit();return key
 def test_simultaneous_claims_are_different(self):
  other=self.add_second_job()
  def reserve(owner):
   c=lab.connect()
   try:return store.claim(c,owner,owner)['id']
   finally:c.close()
  with concurrent.futures.ThreadPoolExecutor(2) as pool:ids=list(pool.map(reserve,['personA','personB']))
  self.assertEqual(set(ids),{self.key,other})
 def test_claim_survives_reconnect_and_expires_safely(self):
  store.claim(self.c,'A','A');self.c.close();self.c=lab.connect();self.assertEqual(store.claim(self.c,'A','A')['id'],self.key)
  self.c.execute('UPDATE review_claims SET expires=0');self.c.commit();self.assertEqual(store.claim(self.c,'B','B')['id'],self.key)
  with self.assertRaises(store.Conflict):store.submit(self.c,self.key,'A',dict(self.data,decision='pass',mode='quick'),require_claim=True)
  self.assertEqual(store.version(self.c,self.key),0)
 def test_quick_pass_records_aggregate_without_inventing_answers(self):
  store.claim(self.c,'A','A');store.submit(self.c,self.key,'A',dict(self.data,decision='pass',mode='quick'),require_claim=True)
  self.assertEqual(json.loads(self.c.execute('SELECT checks FROM reviews').fetchone()[0]),['unknown']*6)
  self.assertEqual(self.c.execute('SELECT method FROM review_methods').fetchone()[0],'quick')
  self.assertIsNone(store.claim(self.c,'B','B')['id'])
  self.assertEqual(len(store.catalog(self.c)),1)
 def test_skip_releases_previous_claim_and_changes_image(self):
  other=self.add_second_job();first=store.claim(self.c,'A','A')['id'];second=store.claim(self.c,'A','A',skip=first)['id']
  self.assertNotEqual(first,second);self.assertEqual(store.claim(self.c,'B','B')['id'],first)
 def test_heartbeat_and_release_do_not_steal_other_claim(self):
  store.claim(self.c,'A','A')
  with self.assertRaises(store.Conflict):store.heartbeat(self.c,self.key,'B')
  store.release(self.c,self.key,'B');self.assertIsNone(store.claim(self.c,'B','B')['id'])
  self.assertTrue(store.heartbeat(self.c,self.key,'A')['ok'])
 def test_idle_heartbeat_cannot_extend_past_last_activity(self):
  import time
  store.claim(self.c,'A','A');activity=time.time()-240
  result=store.heartbeat(self.c,self.key,'A',activity)
  self.assertLessEqual(result['expires'],activity+store.LEASE_SECONDS+0.1)
  with self.assertRaises(store.Conflict):store.heartbeat(self.c,self.key,'A',time.time()-301)
 def add_many_jobs(self,n):
  keys=[self.key]
  for i in range(n-1):
   con=dict(camera='present',source_id='S',portrait_job='P',prompt='batch',seed=900+i,person_id='T')
   key=lab.add_job(self.c,con,'tryon');path=lab.ROOT/lab.FOLDERS[5]/(key+'.png');Image.new('RGB',(32,32),'green').save(path)
   self.c.execute("UPDATE jobs SET status='success',output=?,output_sha256=? WHERE id=?",(str(path),lab.digest(path),key));keys.append(key)
  self.c.commit();return keys
 def test_batch_10_then_refills_10_when_5_remain(self):
  self.add_many_jobs(40);first=store.claim_batch(self.c,'A','검수자 1');self.assertEqual(len(first['ids']),10)
  for key in first['ids'][:5]:store.submit(self.c,key,'A',dict(self.data,mode='quick',decision='pass'),require_claim=True)
  second=store.claim_batch(self.c,'A','검수자 1');self.assertEqual(second['added'],10);self.assertEqual(len(second['ids']),15)
  self.assertEqual(second['ids'][:5],first['ids'][5:]);third=store.claim_batch(self.c,'A','검수자 1');self.assertEqual(third['added'],0)
 def test_batch_is_disjoint_from_other_batches_and_legacy_claims(self):
  self.add_many_jobs(40);legacy=store.claim(self.c,'old','old')['id'];a=store.claim_batch(self.c,'A','검수자 1');b=store.claim_batch(self.c,'B','검수자 2')
  self.assertFalse(set(a['ids'])&set(b['ids']));self.assertNotIn(legacy,a['ids']+b['ids'])
  self.assertEqual(len(store.active_claims(self.c,'A')),3)
 def test_batch_release_and_expiration_return_all_reserved_images(self):
  self.add_many_jobs(20);a=store.claim_batch(self.c,'A','검수자 1');store.release(self.c,a['ids'][0],'A',True)
  self.assertEqual(self.c.execute('SELECT count(*) FROM review_pool WHERE owner=?',('A',)).fetchone()[0],0)
  store.claim_batch(self.c,'A','검수자 1');self.c.execute('UPDATE review_pool SET expires=0');self.c.commit()
  b=store.claim_batch(self.c,'B','검수자 2');self.assertEqual(len(b['ids']),10)
 def test_batch_heartbeat_renews_the_entire_buffer(self):
  self.add_many_jobs(20);a=store.claim_batch(self.c,'A','검수자 1');r=store.heartbeat(self.c,a['ids'][0],'A')
  self.assertEqual(self.c.execute('SELECT count(*) FROM review_pool WHERE expires=?',(r['expires'],)).fetchone()[0],10)
 def test_folded_request_waits_for_an_open_product_reference(self):
  result=store.submit(self.c,self.key,'A',dict(self.data,decision='regenerate',reason='folded'))
  row=self.c.execute('SELECT status,attempts FROM jobs WHERE id=?',(result['child_job'],)).fetchone()
  self.assertEqual(row['status'],'waiting_reference');self.assertEqual(row['attempts'],0)
 def test_waiting_folded_request_reactivates_after_verified_side_is_added(self):
  result=store.submit(self.c,self.key,'A',dict(self.data,decision='regenerate',reason='folded'))
  src=self.c.execute('SELECT path,sha256 FROM sources WHERE id=?',('S',)).fetchone()
  metadata=dict(extra_references=[dict(path=src['path'],sha256=src['sha256'],role='left_side',product='Test frame',temple_state='open')])
  self.c.execute('UPDATE sources SET metadata=? WHERE id=?',(json.dumps(metadata),'S'));self.c.commit()
  from ai_glasses.generation.replan_pending_geometry import migrate
  self.assertEqual(migrate(self.c,waiting_only=True),1)
  child=self.c.execute('SELECT child_job FROM regeneration_requests WHERE id=?',(result['request_id'],)).fetchone()[0]
  self.assertNotEqual(child,result['child_job']);self.assertEqual(self.c.execute('SELECT status FROM jobs WHERE id=?',(child,)).fetchone()[0],'pending')
  self.assertEqual(self.c.execute('SELECT status FROM jobs WHERE id=?',(result['child_job'],)).fetchone()[0],'superseded')
  self.assertEqual(migrate(self.c,waiting_only=True),0)
if __name__=='__main__':unittest.main()

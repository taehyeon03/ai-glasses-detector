"""Meaningful persistence, failure, and leakage checks in an isolated directory."""
import json
from pathlib import Path
import tempfile
import unittest
from ai_glasses.generation import tryon_lab as lab

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=lab.ROOT;lab.ROOT=Path(self.temp.name);self.c=lab.connect()
        self.output=lab.ROOT/lab.FOLDERS[5]/'test.png';self.output.write_bytes(b'isolated test image')
        self.condition=dict(model='test-only',camera='present',person_id='Ptest',source_id='Stest')
        self.key=lab.add_job(self.c,self.condition,'tryon')
        self.c.execute("UPDATE jobs SET status='success',output=? WHERE id=?",(str(self.output),self.key));self.c.commit()
    def tearDown(self):self.c.close();lab.ROOT=self.old;self.temp.cleanup()
    def test_conditions_deduplicate_and_changed_seed_is_new(self):
        self.assertEqual(self.key,lab.add_job(self.c,dict(reversed(list(self.condition.items()))),'tryon'))
        other=lab.add_job(self.c,dict(self.condition,seed=4),'tryon');self.assertNotEqual(self.key,other)
        self.assertEqual(self.c.execute('SELECT count(*) FROM jobs').fetchone()[0],2)
    def test_decisions_persist_and_move_only_generated_image(self):
        decisions=[('hold',['unknown']*6),('exclude',['no']*6),('pass',['yes','yes','na','yes','yes','no'])]
        for decision,checks in decisions:
            lab.review(self.c,self.key,decision,'isolated test',checks,'automated test, not human review')
            self.c.close();self.c=lab.connect()
            self.assertEqual(self.c.execute('SELECT decision FROM reviews').fetchone()[0],decision)
            row=self.c.execute('SELECT output FROM jobs').fetchone();self.assertTrue(Path(row[0]).exists())
        self.assertEqual(self.c.execute('SELECT count(*) FROM review_events').fetchone()[0],3)
        self.assertFalse(self.output.exists())
    def test_unknown_details_cannot_pass(self):
        with self.assertRaises(ValueError):lab.review(self.c,self.key,'pass','',['na']*5+['no'],'test')
        self.assertEqual(self.c.execute('SELECT count(*) FROM reviews').fetchone()[0],0)
    def test_pending_or_failed_image_cannot_be_reviewed(self):
        self.c.execute("UPDATE jobs SET status='failed' WHERE id=?",(self.key,));self.c.commit()
        with self.assertRaises(ValueError):lab.review(self.c,self.key,'hold','',['unknown']*6,'test')
    def test_crash_between_move_and_path_update_is_reconciled(self):
        lab.review(self.c,self.key,'hold','',['unknown']*6,'test')
        actual=lab.ROOT/lab.FOLDERS[8]/(self.key+'.png')
        self.c.execute('UPDATE jobs SET output=?',(str(self.output),));self.c.commit()
        lab.materialize(self.c)
        self.assertEqual(self.c.execute('SELECT output FROM jobs').fetchone()[0],str(actual))
if __name__=='__main__':unittest.main()

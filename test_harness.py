import unittest
import contextlib
import io
from unittest import mock
import tempfile
import json
import struct
import zipfile
from pathlib import Path
import harness as h

class HarnessTests(unittest.TestCase):
    def test_duration(self):
        self.assertEqual(h.duration('2s'),60); self.assertEqual(h.duration('120f'),120); self.assertEqual(h.duration('2m'),3600)
        for v in ('0f','-1','wat','1.5s'):
            with self.assertRaises(ValueError): h.duration(v)
    def test_order_and_release(self):
        events,end=h.compile_recipe({'version':1,'steps':[{'action':'press','buttons':['START','A'],'frames':4,'release_frames':6},{'action':'capture','label':'menu'}]})
        self.assertEqual([e['frame'] for e in events],[1,5,11]); self.assertEqual(events[1]['action'],'up'); self.assertGreater(end,11)
    def test_invalid_recipe(self):
        for steps in ([{'action':'press','buttons':['QUIT']}],[{'action':'wait','frames':True}],[{'action':'capture','label':'../escape'}],[{'action':'capture','label':'x'},{'action':'capture','label':'x'}],[{'action':'reset'}]):
            with self.assertRaises(ValueError): h.compile_recipe({'version':1,'steps':steps})
    def test_requires_capture(self):
        with self.assertRaises(ValueError): h.compile_recipe({'version':1,'steps':[{'action':'wait','frames':3}]})
    def test_state_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); rom=p/'test.z64'; rom.write_bytes(b'original'); state=p/'test.st'; state.write_bytes(b'state')
            meta=Path(str(state)+'.json'); meta.write_text(json.dumps({'rom_sha1':h.digest(rom),'state_sha1':h.digest(state)}))
            self.assertEqual(h.validate_state(state,rom),'sha1_manifest_matches')
            state.write_bytes(b'changed')
            with self.assertRaises(ValueError): h.validate_state(state,rom)
    def test_pj_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); rom=p/'test.z64'; header=bytes.fromhex('80371240')+bytes(range(60)); rom.write_bytes(header)
            state=p/'test.pj.zip'; swapped=b''.join(header[i:i+4][::-1] for i in range(0,64,4))
            with zipfile.ZipFile(state,'w') as z: z.writestr('test.pj',bytes.fromhex('c8a6d823')+struct.pack('<I',0x800000)+swapped)
            self.assertEqual(h.validate_state(state,rom),'pj64_crc_matches_geometry_unverified')
            rom.write_bytes(header[:16]+b'changed!'+header[24:])
            with self.assertRaises(ValueError): h.validate_state(state,rom)
    def test_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'x.png'; h.png(p,1,2,b'\xff\0\0\0\xff\0'); data=p.read_bytes()
            self.assertEqual(data[:8],b'\x89PNG\r\n\x1a\n')
            n=struct.unpack('>I',data[33:37])[0]
            self.assertEqual(h.zlib.decompress(data[41:41+n]),b'\0\0\xff\0\0\xff\0\0')
    def test_callback_releases(self):
        class Fake:
            def __init__(self): self.calls=[]
            def CoreDoCommand(self,*args): self.calls.append(args); return 0
        c=object.__new__(h.Core); c.plan={'events':[{'frame':1,'action':'down','buttons':['START']},{'frame':3,'action':'up','buttons':['START']}],'end_frame':4}
        c.lib=Fake(); c.frame=0; c.loaded=True; c.events=[]; c.pending_save=None; c.error=None
        for i in range(4): c.on_frame(i)
        self.assertEqual([v[:2] for v in c.lib.calls],[(13,40),(14,40),(6,0)])

    def test_readback_black_and_hashes(self):
        class Video:
            def __init__(self, rgb): self.rgb=rgb
            def ReadScreen2(self, dest, width, height, front):
                self.front=front
                width._obj.value=1; height._obj.value=1
                if dest is not None: dest[:]=self.rgb
        with tempfile.TemporaryDirectory() as tmp:
            c=object.__new__(h.Core); c.run=Path(tmp); c.frame=120; c.captures=[]
            for name,rgb,black in [('blank',b'\0\0\0',True),('visible',b'\x80\x40\x20',False)]:
                c.video=Video(rgb); c.capture(name)
                record=c.captures[-1]
                self.assertEqual(record['all_black'],black)
                self.assertEqual(record['rgb_sha1'],h.hashlib.sha1(rgb).hexdigest())
                self.assertEqual(record['png_sha1'],h.digest(record['path']))
                self.assertEqual(c.video.front,0)

    def test_invalid_capture_retains_evidence_and_failure_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); rom=root/'test.z64'
            rom.write_bytes(bytes.fromhex('80371240')+bytes(60))
            def worker(args, **kwargs):
                plan=json.loads(Path(args[-1]).read_text())
                Path(plan['run_dir'],'result.json').write_text(json.dumps({
                    'status':'capture_invalid','capture_pass':False,
                    'semantic_pass':None,'review_required':True,
                    'captures':[{'frame':1,'all_black':True}]}))
                return mock.Mock(returncode=1)
            with mock.patch.dict(h.os.environ,{'SSSV_TEST_DIR':tmp}), mock.patch.object(h.subprocess,'run',side_effect=worker), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(h.main(['capture',str(rom),'1f']),1)
            summary=json.loads(next(root.rglob('summary.json')).read_text())
            self.assertEqual(summary['status'],'capture_invalid')
            self.assertFalse(summary['capture_pass'])
            self.assertIsNone(summary['semantic_pass'])
            self.assertTrue(summary['captures'][0]['all_black'])

    def test_known_scene_schedule_and_cold_boot(self):
        recipe=json.loads((h.ROOT/'recipes/known-scene.json').read_text())
        events,end=h.compile_recipe(recipe)
        self.assertTrue(recipe['cold_boot_only'])
        self.assertEqual([(e['frame'],e['action']) for e in events],[(120,'capture'),(180,'capture')])
        self.assertGreater(end,180)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            h.main(['recipe',str(h.ROOT/'recipes/known-scene.json'),'--state','some.st','--dry-run'])

    def test_worker_crash_overrides_completed_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); rom=root/'test.z64'
            rom.write_bytes(bytes.fromhex('80371240')+bytes(60))
            def worker(args, **kwargs):
                plan=json.loads(Path(args[-1]).read_text())
                Path(plan['run_dir'],'result.json').write_text(json.dumps({'status':'capture_complete'}))
                return mock.Mock(returncode=139)
            with mock.patch.dict(h.os.environ,{'SSSV_TEST_DIR':tmp}), mock.patch.object(h.subprocess,'run',side_effect=worker), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(h.main(['capture',str(rom),'120f']),1)
            self.assertEqual(json.loads(next(root.rglob('summary.json')).read_text())['status'],'failed')

    def test_wait_for_disk_save(self):
        class Fake:
            def __init__(self): self.calls=[]
            def CoreDoCommand(self,*args): self.calls.append(args); return 0
        c=object.__new__(h.Core)
        c.plan={'events':[],'end_frame':1}; c.lib=Fake(); c.frame=0
        c.loaded=True; c.events=[]; c.error=None
        c.pending_save=Path('/private/test.st'); c.save_written=set(); c.saves=[]
        c.on_frame(0)
        self.assertEqual(c.lib.calls,[])
        c.save_written.add('test.st'); c.on_frame(1)
        self.assertEqual(c.saves,[str(Path('/private/test.st'))])
        self.assertEqual(c.lib.calls,[(6,0,None)])

    def test_missing_rom_has_clear_error(self):
        errors = io.StringIO()
        with mock.patch.object(h, 'DEFAULT_ROM', None), contextlib.redirect_stderr(errors):
            with self.assertRaises(SystemExit) as result:
                h.main(['capture', '1f', '--dry-run'])
        self.assertEqual(result.exception.code, 2)
        self.assertIn('provide a ROM path or set SSSV_ROM', errors.getvalue())

    def test_explicit_rom_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            rom = Path(tmp) / 'synthetic.z64'
            rom.write_bytes(bytes.fromhex('80371240') + bytes(60))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = h.main(['capture', str(rom), '1f', '--dry-run'])
            plan = json.loads(output.getvalue())
            self.assertEqual(result, 0)
            self.assertEqual(plan['rom_sha1'], h.digest(rom))
            self.assertEqual(plan['events'][0]['frame'], 1)
            self.assertEqual(plan['state_identity'], 'cold_boot')
            self.assertEqual(list(Path(tmp).iterdir()), [rom])

if __name__=='__main__': unittest.main()

import contextlib
import io
import json
import random
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

import harness as h
import semantic as s

W, H = 64, 48


def scene(kind):
    """Synthetic RGB frames: no game imagery."""
    px = bytearray()
    for y in range(H):
        for x in range(W):
            if kind == 'a':    # horizontal gradient with a bright square
                v = x * 3 + (120 if 10 <= x < 30 and 8 <= y < 28 else 0)
                px += bytes((min(v, 255), 40, 90))
            elif kind == 'b':  # vertical stripes, clearly different layout
                px += bytes((200, 200, 30)) if (x // 8) % 2 else bytes((10, 10, 120))
            else:
                px += bytes((0, 0, 0))
    return bytes(px)


def write(path, rgb):
    h.png(path, W, H, rgb)   # harness writer
    return str(path)


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))


def raw_png(path, ctype, depth=8, inter=0, rows=None, w=2, hh=2):
    ch = {0: 1, 2: 3, 4: 2, 6: 4}.get(ctype, 1)
    rows = rows if rows is not None else b''.join(b'\0' + bytes(w * ch) for _ in range(hh))
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, hh, depth, ctype, 0, 0, inter))
                           + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))
    return str(path)


def ref_for(path, **kw):
    return s.load_reference('x', dict(path=path, **kw))


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def check(self, cap, ref):
        return s.compare(cap, ref)

    def test_identical(self):
        a = write(self.dir / 'a.png', scene('a'))
        r = self.check(a, ref_for(a))
        self.assertTrue(r['pass']); self.assertEqual(r['mean_luma_diff'], 0); self.assertEqual(r['dhash_distance'], 0)

    def test_noise_within_tolerance(self):
        rng = random.Random(1)
        noisy = bytes(max(0, min(255, b + rng.randint(-6, 6))) for b in scene('a'))
        a = write(self.dir / 'a.png', scene('a')); n = write(self.dir / 'n.png', noisy)
        r = self.check(n, ref_for(a))
        self.assertTrue(r['pass']); self.assertGreater(r['mean_luma_diff'], 0)
        self.assertFalse(self.check(n, ref_for(a, tolerance=0, mode='luma'))['pass'])

    def test_different_scene(self):
        a = write(self.dir / 'a.png', scene('a')); b = write(self.dir / 'b.png', scene('b'))
        r = self.check(b, ref_for(a))
        self.assertFalse(r['pass'])
        self.assertFalse(self.check(b, ref_for(a, mode='luma'))['pass'])

    def test_roi_masks_hud(self):
        base = bytearray(scene('a')); hud = bytearray(base)
        for y in range(0, 8):                       # strip "HUD" changes (harness.png stores rows bottom-up, so it shows at the bottom)
            for x in range(W):
                hud[(y * W + x) * 3:(y * W + x) * 3 + 3] = b'\xff\xff\xff'
        a = write(self.dir / 'a.png', bytes(base)); b = write(self.dir / 'hud.png', bytes(hud))
        self.assertFalse(self.check(b, ref_for(a, mode='luma', tolerance=1))['pass'])
        r = self.check(b, ref_for(a, mode='luma', tolerance=1, roi=[0, 0, 1, 0.75]))
        self.assertTrue(r['pass']); self.assertEqual(r['mean_luma_diff'], 0)

    def test_unsupported_png(self):
        for ctype, depth, inter in ((6, 8, 0), (0, 8, 0), (2, 16, 0), (2, 8, 1)):
            p = raw_png(self.dir / 'u.png', ctype, depth, inter)
            with self.assertRaisesRegex(ValueError, 'unsupported PNG'):
                s.load_reference('x', p)
        (self.dir / 'bad.png').write_bytes(b'not a png')
        with self.assertRaises(ValueError): s.load_reference('x', str(self.dir / 'bad.png'))

    def test_filters_decode(self):
        row0 = bytes([10, 20, 30, 40, 50, 60]); row1 = bytes([11, 22, 33, 44, 55, 66])
        for ft in (1, 2, 3, 4):
            def filt(row, prev):
                out = bytearray()
                for i, v in enumerate(row):
                    a = row[i - 3] if i >= 3 else 0; b = prev[i]; c = prev[i - 3] if i >= 3 else 0
                    pred = {1: a, 2: b, 3: (a + b) >> 1}.get(ft)
                    if ft == 4:
                        p = a + b - c; pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                        pred = a if pa <= pb and pa <= pc else b if pb <= pc else c
                    out.append((v - pred) & 255)
                return bytes(out)
            data = bytes([ft]) + filt(row0, bytes(6)) + bytes([ft]) + filt(row1, row0)
            p = raw_png(self.dir / 'f.png', 2, rows=data)
            self.assertEqual(s.decode_png(Path(p).read_bytes()), (2, 2, row0 + row1))

    def test_bad_config(self):
        a = write(self.dir / 'a.png', scene('a'))
        for kw in ({'mode': 'x'}, {'tolerance': -1}, {'roi': [0, 0, 0, 1]}, {'roi': [0, 0, 1]}, {'hash_tolerance': 99}):
            with self.assertRaises(ValueError): ref_for(a, **kw)

    def test_no_reference_is_null(self):
        self.assertEqual(s.evaluate([], {}), (None, {}))

    def run_main(self, args, ref_scene):
        rom = self.dir / 'test.z64'; rom.write_bytes(bytes.fromhex('80371240') + bytes(60))
        def worker(argv, **kw):
            plan = json.loads(Path(argv[-1]).read_text()); run = Path(plan['run_dir'])
            cap = write(run / 'capture.png', ref_scene)
            Path(run, 'result.json').write_text(json.dumps({'status': 'capture_complete', 'capture_pass': True, 'semantic_pass': None,
                'captures': [{'path': cap, 'frame': 120, 'all_black': False}], 'core_errors': []}))
            return mock.Mock(returncode=0)
        out = self.dir / 'out'
        with mock.patch.dict(h.os.environ, {'SSSV_TEST_DIR': str(out)}), mock.patch.object(h.subprocess, 'run', side_effect=worker), \
                contextlib.redirect_stdout(io.StringIO()):
            code = h.main(['capture', str(rom), '120f'] + args)
        return code, json.loads(max(out.rglob('summary.json'), key=lambda q: q.stat().st_mtime_ns).read_text())

    def test_main_pass_mismatch_and_null(self):
        a = write(self.dir / 'ref.png', scene('a'))
        code, summary = self.run_main([], scene('a'))
        self.assertEqual(code, 0); self.assertIsNone(summary['semantic_pass']); self.assertNotIn('semantic', summary)
        code, summary = self.run_main(['--reference', 'capture=' + a], scene('a'))
        self.assertEqual(code, 0); self.assertIs(summary['semantic_pass'], True)
        self.assertEqual(summary['semantic']['capture']['dhash_distance'], 0)
        code, summary = self.run_main(['--reference', 'capture=' + a], scene('b'))
        self.assertEqual(code, 2); self.assertEqual(summary['status'], 'semantic_mismatch')
        self.assertIs(summary['semantic_pass'], False); self.assertTrue(summary['captures'])

    def test_main_rejects_bad_reference_before_run(self):
        rom = self.dir / 'test.z64'; rom.write_bytes(bytes.fromhex('80371240') + bytes(60))
        bad = raw_png(self.dir / 'rgba.png', 6)
        with mock.patch.object(h.subprocess, 'run') as run, contextlib.redirect_stderr(io.StringIO()):
            for ref in ('capture=' + bad, 'nolabel=' + bad):
                with self.assertRaises(SystemExit): h.main(['capture', str(rom), '120f', '--reference', ref])
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()

"""Optional reference-image comparison for harness captures, stdlib only.

Decodes only 8-bit non-interlaced RGB PNGs (what harness.png writes) and
compares a capture to a user-supplied reference with a coarse luma grid
and/or a dHash. Passing means "similar to the reference you gave", nothing more.
"""
import struct
import zlib
from pathlib import Path

MODES = ('luma', 'dhash', 'both')
DEFAULTS = {'mode': 'both', 'tolerance': 12.0, 'hash_tolerance': 10, 'roi': None}
GRID = (32, 24)   # luma grid cells (w, h)
HASH = (9, 8)     # dHash grid -> 64 bits


def decode_png(data):
    """Return (width, height, rgb bytes). Raises ValueError on anything unsupported."""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not a PNG file')
    pos, ihdr, idat = 8, None, []
    while pos + 8 <= len(data):
        n, kind = struct.unpack('>I4s', data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if len(body) != n or data[pos + 8 + n:pos + 12 + n] != struct.pack('>I', zlib.crc32(kind + body)):
            raise ValueError('corrupt PNG chunk ' + kind.decode('latin1'))
        if kind == b'IHDR':
            ihdr = struct.unpack('>IIBBBBB', body)
        elif kind == b'IDAT':
            idat.append(body)
        elif kind == b'IEND':
            break
        pos += 12 + n
    if not ihdr or not idat:
        raise ValueError('PNG missing IHDR or IDAT')
    w, h, depth, ctype, comp, filt, inter = ihdr
    if (depth, ctype, inter) != (8, 2, 0) or comp or filt:
        raise ValueError('unsupported PNG (bit depth %d, colour type %d, interlace %d): '
                         'only 8-bit RGB, non-interlaced is supported' % (depth, ctype, inter))
    if not 0 < w <= 8192 or not 0 < h <= 8192:
        raise ValueError('unsupported PNG dimensions')
    raw = zlib.decompress(b''.join(idat))
    stride = w * 3
    if len(raw) != h * (stride + 1):
        raise ValueError('PNG pixel data has the wrong length')
    out, prev = bytearray(), bytearray(stride)
    for y in range(h):
        ft = raw[y * (stride + 1)]
        row = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if ft == 1:
            for i in range(3, stride):
                row[i] = (row[i] + row[i - 3]) & 255
        elif ft == 2:
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 255
        elif ft == 3:
            for i in range(stride):
                row[i] = (row[i] + (((row[i - 3] if i >= 3 else 0) + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                a = row[i - 3] if i >= 3 else 0
                b = prev[i]
                c = prev[i - 3] if i >= 3 else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                row[i] = (row[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        elif ft != 0:
            raise ValueError('bad PNG filter type %d' % ft)
        out += row
        prev = row
    return w, h, bytes(out)


def grid_luma(w, h, rgb, cols, rows, roi=None):
    """Box-average luma (0-255) of the ROI (fractions x0,y0,x1,y1) onto cols x rows cells."""
    x0, y0, x1, y1 = 0, 0, w, h
    if roi:
        x0, y0 = int(roi[0] * w), int(roi[1] * h)
        x1, y1 = max(x0 + 1, round(roi[2] * w)), max(y0 + 1, round(roi[3] * h))
    x1, y1 = min(x1, w), min(y1, h)
    rw, rh = x1 - x0, y1 - y0
    if rw < 1 or rh < 1:
        raise ValueError('region of interest is empty')
    luma = [(299 * r + 587 * g + 114 * b) / 1000.0
            for r, g, b in zip(rgb[0::3], rgb[1::3], rgb[2::3])]
    cells = []
    for r in range(rows):
        ya = y0 + r * rh // rows
        yb = max(ya + 1, y0 + (r + 1) * rh // rows)
        for c in range(cols):
            xa = x0 + c * rw // cols
            xb = max(xa + 1, x0 + (c + 1) * rw // cols)
            total = sum(sum(luma[y * w + xa:y * w + xb]) for y in range(ya, yb))
            cells.append(total / ((yb - ya) * (xb - xa)))
    return cells


def dhash(cells, cols=HASH[0], rows=HASH[1]):
    return [1 if cells[r * cols + c] > cells[r * cols + c + 1] else 0
            for r in range(rows) for c in range(cols - 1)]


def normalize(label, spec):
    """Turn a path string or dict into a validated reference config."""
    cfg = dict(DEFAULTS)
    cfg.update({'path': spec} if isinstance(spec, str) else dict(spec))
    if not cfg.get('path') or not isinstance(cfg['path'], str):
        raise ValueError('reference %s needs a path' % label)
    if cfg['mode'] not in MODES:
        raise ValueError('reference %s: mode must be one of %s' % (label, ', '.join(MODES)))
    tol = cfg['tolerance']
    if isinstance(tol, bool) or not isinstance(tol, (int, float)) or not 0 <= tol <= 255:
        raise ValueError('reference %s: tolerance must be 0-255 (mean luma difference)' % label)
    if type(cfg['hash_tolerance']) is not int or not 0 <= cfg['hash_tolerance'] <= 64:
        raise ValueError('reference %s: hash_tolerance must be an integer 0-64 (bits)' % label)
    roi = cfg['roi']
    if roi is not None:
        if (not isinstance(roi, (list, tuple)) or len(roi) != 4
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in roi)
                or not (0 <= roi[0] < roi[2] <= 1 and 0 <= roi[1] < roi[3] <= 1)):
            raise ValueError('reference %s: roi must be [x0,y0,x1,y1] fractions, 0<=x0<x1<=1 and 0<=y0<y1<=1' % label)
        cfg['roi'] = list(roi)
    cfg['path'] = str(Path(cfg['path']).expanduser().resolve())
    return cfg


def load_reference(label, spec):
    """Normalize and decode a reference up front so bad input fails before any emulator run."""
    cfg = normalize(label, spec)
    try:
        cfg['_image'] = decode_png(Path(cfg['path']).read_bytes())
    except OSError as e:
        raise ValueError('reference %s: %s' % (label, e))
    except (ValueError, zlib.error) as e:
        raise ValueError('reference %s (%s): %s' % (label, cfg['path'], e))
    return cfg


def compare(capture_path, ref):
    """Compare a capture PNG to a loaded reference. Returns a JSON-safe metrics dict."""
    w, h, rgb = decode_png(Path(capture_path).read_bytes())
    rw, rh, rrgb = ref['_image']
    roi = ref['roi']
    a, b = grid_luma(w, h, rgb, *GRID, roi), grid_luma(rw, rh, rrgb, *GRID, roi)
    mad = sum(abs(x - y) for x, y in zip(a, b)) / len(a)
    ha = dhash(grid_luma(w, h, rgb, *HASH, roi))
    hb = dhash(grid_luma(rw, rh, rrgb, *HASH, roi))
    ham = sum(x != y for x, y in zip(ha, hb))
    ok_l, ok_h = mad <= ref['tolerance'], ham <= ref['hash_tolerance']
    passed = {'luma': ok_l, 'dhash': ok_h, 'both': ok_l and ok_h}[ref['mode']]
    return {'reference': ref['path'], 'mode': ref['mode'], 'roi': roi,
            'mean_luma_diff': round(mad, 3), 'luma_tolerance': ref['tolerance'],
            'dhash_distance': ham, 'dhash_tolerance': ref['hash_tolerance'],
            'capture_size': [w, h], 'reference_size': [rw, rh], 'pass': passed}


def evaluate(captures, refs):
    """Return (semantic_pass, per-label report). semantic_pass is None when refs is empty."""
    if not refs:
        return None, {}
    report = {}
    by_label = {Path(c['path']).stem: c for c in captures}
    for label, ref in refs.items():
        if label not in by_label:
            report[label] = {'pass': False, 'error': 'no capture with this label'}
            continue
        try:
            report[label] = compare(by_label[label]['path'], ref)
        except (ValueError, OSError, zlib.error) as e:
            report[label] = {'pass': False, 'error': str(e)}
    return all(r['pass'] for r in report.values()), report

#!/usr/bin/env python3
"""
Fingerprint distance / threshold evaluation for the Dashcam project.

Usage:  python evaluate.py <original_dashcam.webm> [--out results]

1. Applies video transformations to the original (ffmpeg): benign (should still MATCH), tamper (should be REJECTED)
   and stress (reported only).
2. For every transformed video, reads the frame-index barcode exactly like the Decoder (24 blocks + CRC-8), and takes
   the first K frames carrying each index (best-of-K, like the Decoder).
3. Computes, for each reference/candidate frame pair, 18 distance measures (aHash, dHash, pHash, wHash with Hamming and
   normalised Hamming; ssdeep; TLSH; project signature with L1 / L2 / cosine / altered-block count; 16x16 thumbnail with
   L1 / L2 / cosine).
4. Chooses a threshold per metric (maximises balanced accuracy of benign-vs-(tamper + impostor)), reports AUC, TPR/FPR,
   and the pass rate of every transformation at that threshold.
"""
import argparse, os, subprocess, sys, itertools, json
import numpy as np, pandas as pd, cv2, imagehash, ppdeep
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import tlsh
    HAVE_TLSH = True
except ImportError:          # TLSH needs a C++ build; the rest of the evaluation still runs without it
    HAVE_TLSH = False
    print('NOTE: python-tlsh is not installed; the TLSH metric is skipped.')

STRIP, BITS, GRID, SW, SH, K = 0.06, 24, 8, 320, 160, 5
REF_STEP = 1  # evaluate every index

# ---- make the decoder's validator importable (for the altered-block rule) --------------------------------------
for cand in ('/mnt/user-data/outputs/Decoder_App', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Decoder_App')):
    if os.path.exists(os.path.join(cand, 'core', 'integrity_validator.py')):
        sys.path.insert(0, cand); break
from core.integrity_validator import altered_cells, PROFILES

# ------------------------------------------------------------------------------------------------ transformations
# group: benign = a genuine video that was only re-processed (must still match)
#        tamper = content was changed (must be rejected)
#        stress = harsher processing, reported only
def vf(expr): return ['-vf', expr]
TRANSFORMS = {
    # name: (group, ffmpeg args)
    'reencode_crf25':   ('benign', ['-c:v', 'libvpx', '-crf', '25', '-b:v', '2M']),
    'reencode_crf40':   ('benign', ['-c:v', 'libvpx', '-crf', '40', '-b:v', '600k']),
    'scale_640x360':    ('benign', vf('scale=640:360') + ['-c:v', 'libvpx', '-b:v', '2M']),
    'bright_+5%':       ('benign', vf('eq=brightness=0.05') + ['-c:v', 'libvpx', '-b:v', '4M']),
    'dark_-5%':         ('benign', vf('eq=brightness=-0.05') + ['-c:v', 'libvpx', '-b:v', '4M']),
    'noise_mild':       ('benign', vf('noise=alls=6:allf=t') + ['-c:v', 'libvpx', '-b:v', '5M']),
    'sticker_small':    ('tamper', vf('drawbox=x=iw*0.55:y=ih*0.55:w=iw*0.08:h=ih*0.12:color=red@1:t=fill') + ['-c:v', 'libvpx', '-b:v', '5M']),
    'sticker_large':    ('tamper', vf('drawbox=x=iw*0.30:y=ih*0.40:w=iw*0.25:h=ih*0.25:color=blue@1:t=fill') + ['-c:v', 'libvpx', '-b:v', '5M']),
    'blur_region':      ('tamper', vf('split[a][b];[b]crop=iw*0.30:ih*0.30:iw*0.20:ih*0.50,gblur=sigma=12[c];[a][c]overlay=main_w*0.20:main_h*0.50') + ['-c:v', 'libvpx', '-b:v', '5M']),
    'blur_full':        ('tamper', vf('gblur=sigma=5') + ['-c:v', 'libvpx', '-b:v', '5M']),
    'bright_+20%':      ('stress', vf('eq=brightness=0.20') + ['-c:v', 'libvpx', '-b:v', '4M']),
    'dark_-20%':        ('stress', vf('eq=brightness=-0.20') + ['-c:v', 'libvpx', '-b:v', '4M']),
    'noise_strong':     ('stress', vf('noise=alls=30:allf=t') + ['-c:v', 'libvpx', '-b:v', '5M']),
    'scale_320x180':    ('stress', vf('scale=320:180') + ['-c:v', 'libvpx', '-b:v', '1M']),
    'contrast_1.3':     ('stress', vf('eq=contrast=1.3') + ['-c:v', 'libvpx', '-b:v', '4M']),
    'frame_drop_50%':   ('stress', vf("select='not(mod(n,2))',setpts=N/(FRAME_RATE*TB)") + ['-r', '30', '-c:v', 'libvpx', '-b:v', '5M']),
    'time_shift_0.4s':  ('stress', ['-ss', '0.4', '-c:v', 'libvpx', '-b:v', '5M']),
    'cut_5s_to_9s':     ('stress', vf("select='lt(t,5)+gte(t,9)',setpts=N/(FRAME_RATE*TB)") + ['-r', '30', '-c:v', 'libvpx', '-b:v', '5M']),
}

def make_variants(src, outdir):
    os.makedirs(outdir, exist_ok=True)
    paths = {}
    for name, (grp, args) in TRANSFORMS.items():
        dst = os.path.join(outdir, name.replace('%', 'pct') + '.webm')
        if not os.path.exists(dst):
            tmp = dst + '.part'                      # write to a temporary name so an interrupted run never leaves a half file
            cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-i', src] + args + ['-an', '-f', 'webm', tmp]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode: print(f'  ! {name} failed: {r.stderr.strip()[:200]}'); continue
            os.replace(tmp, dst)
        paths[name] = dst
    return paths

# ------------------------------------------------------------------------------------------------ barcode reader
def crc8(bs):
    c = 0
    for b in bs:
        c ^= b
        for _ in range(8): c = ((c << 1) ^ 0x07) & 0xFF if c & 0x80 else (c << 1) & 0xFF
    return c

def read_index(frame):
    h, w = frame.shape[:2]
    sh = round(h * STRIP); bw = w / BITS
    y0, y1 = int(sh * .25), int(sh * .75)
    bits = ''
    for i in range(BITS):
        x0, x1 = int(i * bw + bw * .25), int(i * bw + bw * .75)
        bits += '1' if frame[y0:y1, x0:x1, 1].mean() > 127 else '0'      # green channel, as in the Decoder
    hi, lo, crc = int(bits[:8], 2), int(bits[8:16], 2), int(bits[16:], 2)
    if crc8([hi, lo]) != crc: return None
    return (hi * 256 + lo) or None

def read_video(path):
    """index -> list of first K frames (BGR, resized to 1280x720 so that all videos share one geometry)."""
    cap = cv2.VideoCapture(path); frames = {}; total = unreadable = 0
    while True:
        ok, f = cap.read()
        if not ok: break
        total += 1
        idx = read_index(f)
        if idx is None: unreadable += 1; continue
        lst = frames.setdefault(idx, [])
        if len(lst) < K:
            lst.append(cv2.resize(f, (1280, 720), interpolation=cv2.INTER_AREA) if f.shape[1] != 1280 else f)
    cap.release()
    return frames, total, unreadable

# ------------------------------------------------------------------------------------------------ fingerprints
def content(frame):                      # remove the barcode strip, like the Encoder
    h = frame.shape[0]; return frame[round(h * STRIP):]

def luminance(small_bgr):
    b, g, r = small_bgr[..., 0].astype(np.float32), small_bgr[..., 1].astype(np.float32), small_bgr[..., 2].astype(np.float32)
    return .299 * r + .587 * g + .114 * b

def project_signature(frame):            # same algorithm as the JS (8x8 blocks of mean luminance + edge detail)
    small = cv2.resize(content(frame), (SW, SH), interpolation=cv2.INTER_AREA)
    Y = luminance(small); cw, ch = SW // GRID, SH // GRID; out = []
    for gy in range(GRID):
        for gx in range(GRID):
            blk = Y[gy * ch:(gy + 1) * ch, gx * cw:(gx + 1) * cw]
            g = np.abs(np.diff(blk, axis=1))[:-1, :].sum() + np.abs(np.diff(blk, axis=0))[:, :-1].sum()
            n = (ch - 1) * (cw - 1)
            out += [int(round(blk.mean())), min(255, int(round(g / n * 8)))]
    return np.array(out, dtype=np.float64)

def sig_hex(v): return ''.join(f'{int(x):02x}' for x in v)

def fingerprint(frame):
    c = content(frame)
    gray = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
    pil = Image.fromarray(gray)
    raw = cv2.resize(gray, (96, 96), interpolation=cv2.INTER_AREA).tobytes()     # bytes for ssdeep / TLSH
    thumb = cv2.resize(gray, (16, 16), interpolation=cv2.INTER_AREA).astype(np.float64).ravel()
    sig = project_signature(frame)
    return {
        'ahash': imagehash.average_hash(pil, 8), 'dhash': imagehash.dhash(pil, 8),
        'phash': imagehash.phash(pil, 8, 4), 'whash': imagehash.whash(pil, 8),
        'ssdeep': ppdeep.hash(raw), 'tlsh': tlsh.hash(raw) if HAVE_TLSH else None,
        'sig': sig, 'thumb': thumb,
    }

def l1(a, b): return float(np.abs(a - b).sum())
def l2(a, b): return float(np.sqrt(((a - b) ** 2).sum()))
def cosd(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return 1.0 if na == 0 or nb == 0 else float(1 - a @ b / (na * nb))

STRICT = PROFILES['strict']
def distances(f1, f2):
    d = {}
    for m in ('ahash', 'dhash', 'phash', 'whash'):
        h = int(f1[m] - f2[m]); d[f'{m}_hamming'] = h; d[f'{m}_norm'] = h / 64
    d['ssdeep_dist'] = 100 - ppdeep.compare(f1['ssdeep'], f2['ssdeep'])           # 0 = identical, 100 = unrelated
    if HAVE_TLSH: d['tlsh_dist'] = tlsh.diff(f1['tlsh'], f2['tlsh'])
    d['sig_l1'], d['sig_l2'], d['sig_cos'] = l1(f1['sig'], f2['sig']), l2(f1['sig'], f2['sig']), cosd(f1['sig'], f2['sig'])
    d['sig_blocks'] = len(altered_cells(sig_hex(f1['sig']), sig_hex(f2['sig']), STRICT))
    d['thumb_l1'], d['thumb_l2'], d['thumb_cos'] = l1(f1['thumb'], f2['thumb']), l2(f1['thumb'], f2['thumb']), cosd(f1['thumb'], f2['thumb'])
    return d

# ------------------------------------------------------------------------------------------------ threshold selection
def auc_lower_is_match(pos, neg):
    """P(distance of a matching pair < distance of a non-matching pair); ties count 0.5."""
    pos, neg = np.asarray(pos), np.asarray(neg)
    gt = (neg[None, :] > pos[:, None]).mean(); eq = (neg[None, :] == pos[:, None]).mean()
    return float(gt + .5 * eq)

def best_threshold(pos, neg):
    """Accept when distance <= t. Maximise balanced accuracy = (TPR + TNR) / 2."""
    pos, neg = np.asarray(pos), np.asarray(neg)
    cands = np.unique(np.concatenate([pos, neg]))
    best = None
    for t in cands:
        tpr = (pos <= t).mean(); tnr = (neg > t).mean(); ba = (tpr + tnr) / 2
        if best is None or ba > best[0] + 1e-12 or (abs(ba - best[0]) < 1e-12 and t > best[1]):
            best = (ba, float(t), float(tpr), float(1 - tnr))
    return best  # balanced_acc, threshold, TPR, FPR

# ------------------------------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('video'); ap.add_argument('--out', default='results')
    ap.add_argument('--impostors', type=int, default=3, help='impostor pairs per reference frame')
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)

    print('Reading reference video...')
    ref_frames, total, bad = read_video(a.video)
    ref_idx = sorted(ref_frames)
    print(f'  {total} video frames, {bad} without readable barcode, {len(ref_idx)} distinct indexes: {ref_idx[0]}..{ref_idx[-1]}')
    if len(ref_idx) < 5: sys.exit('Too few indexed frames. Is this a video recorded by the Encoder?')
    ref_fp = {i: fingerprint(ref_frames[i][0]) for i in ref_idx}

    print('Creating transformed videos with ffmpeg...')
    variants = make_variants(a.video, os.path.join(a.out, 'variants'))

    rows, coverage = [], []
    rng = np.random.default_rng(1)
    for name, path in variants.items():
        grp = TRANSFORMS[name][0]
        fr, tot, unreadable = read_video(path)
        found = [i for i in ref_idx if i in fr]
        coverage.append({'transform': name, 'group': grp, 'indexes_expected': len(ref_idx), 'indexes_found': len(found),
                         'indexes_missing': len(ref_idx) - len(found), 'frames_read': tot, 'frames_unreadable_barcode': unreadable})
        print(f'  {name:16s} [{grp:6s}] indexes found {len(found)}/{len(ref_idx)}')
        for i in found:
            cands = [fingerprint(f) for f in fr[i]]                        # best-of-K candidates
            dl = [distances(ref_fp[i], c) for c in cands]
            best = {k: min(x[k] for x in dl) for k in dl[0]}
            rows.append({'transform': name, 'group': grp, 'index': i, 'kind': 'genuine', **best})
    # impostors: reference frame i against a different frame j of the original video (frames of the same scene, other moment)
    for i in ref_idx:
        others = [j for j in ref_idx if abs(j - i) >= 3]
        for j in rng.choice(others, size=min(a.impostors, len(others)), replace=False):
            rows.append({'transform': 'impostor_other_frame', 'group': 'impostor', 'index': i, 'kind': 'impostor', **distances(ref_fp[i], ref_fp[int(j)])})

    df = pd.DataFrame(rows); df.to_csv(os.path.join(a.out, 'pairs.csv'), index=False)
    pd.DataFrame(coverage).to_csv(os.path.join(a.out, 'coverage.csv'), index=False)

    metrics = [c for c in df.columns if c not in ('transform', 'group', 'index', 'kind')]
    pos_mask = df.group == 'benign'; neg_mask = df.group.isin(['tamper', 'impostor'])
    th = []
    for m in metrics:
        pos, neg = df.loc[pos_mask, m].values, df.loc[neg_mask, m].values
        ba, t, tpr, fpr = best_threshold(pos, neg)
        tam = df.loc[df.group == 'tamper', m].values; imp = df.loc[df.group == 'impostor', m].values
        th.append({'metric': m, 'AUC': round(auc_lower_is_match(pos, neg), 4), 'threshold(accept if <=)': round(t, 4),
                   'balanced_acc': round(ba, 4), 'benign_accepted(TPR)': round(tpr, 4),
                   'tamper_accepted(FPR)': round(float((tam <= t).mean()), 4), 'impostor_accepted(FPR)': round(float((imp <= t).mean()), 4),
                   'benign_max': round(float(pos.max()), 4), 'tamper_min': round(float(tam.min()), 4), 'impostor_min': round(float(imp.min()), 4)})
    thdf = pd.DataFrame(th)
    thdf['verdict'] = thdf['AUC'].apply(lambda v: 'good' if v >= .9 else 'weak' if v >= .7 else 'NOT discriminative (threshold not meaningful)')
    thdf = thdf.sort_values('AUC', ascending=False); thdf.to_csv(os.path.join(a.out, 'thresholds.csv'), index=False)

    # pass rate of every transformation at each metric's threshold
    tmap = {r['metric']: r['threshold(accept if <=)'] for r in th}
    pr = (df.assign(**{m: df[m] <= tmap[m] for m in metrics}).groupby(['group', 'transform'])[metrics].mean().round(3))
    pr.to_csv(os.path.join(a.out, 'robustness_pass_rates.csv'))

    plot(df, thdf, metrics, a.out)
    pd.set_option('display.width', 250); pd.set_option('display.max_columns', 30)
    print('\n=== Threshold per metric (sorted by AUC) ===\n', thdf.to_string(index=False))
    print('\nResults written to', a.out)

def plot(df, thdf, metrics, out):
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    show = ['ahash_norm', 'dhash_norm', 'phash_norm', 'whash_norm', 'ssdeep_dist', 'tlsh_dist', 'sig_l1', 'sig_cos', 'sig_blocks', 'thumb_l2', 'thumb_cos']
    show = [m for m in show if m in df.columns]
    fig, axs = plt.subplots(3, 4, figsize=(15, 9)); axs = axs.ravel()
    col = {'benign': '#2E7D32', 'tamper': '#C62828', 'impostor': '#6A1B9A', 'stress': '#9E9E9E'}
    for ax, m in zip(axs, show):
        data = [df.loc[df.group == g, m].values for g in ('benign', 'tamper', 'impostor')]
        bp = ax.boxplot(data, tick_labels=['benign', 'tamper', 'impostor'], patch_artist=True, showfliers=True)
        for p, g in zip(bp['boxes'], ('benign', 'tamper', 'impostor')): p.set_facecolor(col[g]); p.set_alpha(.6)
        t = thdf.loc[thdf.metric == m, 'threshold(accept if <=)'].iloc[0]
        ax.axhline(t, color='k', ls='--', lw=1); ax.set_title(f'{m}  (threshold {t:g})', fontsize=9)
    for ax in axs[len(show):]: ax.axis('off')
    fig.suptitle('Distance distributions: benign vs tamper vs impostor (dashed = chosen threshold)'); fig.tight_layout()
    fig.savefig(os.path.join(out, 'distributions.png'), dpi=130); plt.close(fig)

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
tube_stand.py - parametric, stackable single-tube stand for conical centrifuge tubes.

The stand is a solid of revolution built from a 2D cross-section (r, z):

    collar (ring) ── holds the tube body, with 4 small inward ribs
       │
    seat (inner cone) ── the tube's conical tip rests on its lower lip
       │
    skirt + flange ── wide, thin flange on the table

A C-shaped front opening is cut out: a wedge through the collar and seat, and a slot of
constant width through the skirt and flange. For stacking, five tabs sit on the collar rim,
and matching pockets are cut into the flat landing underneath. One tab is wider than the
others, so the stands nest one way only.

Requires Python 3.8+ and numpy (plus matplotlib only for --text).

Usage
-----
    # describe the tube; everything else is derived from it
    python tube_stand.py --od-top 29.72 --od-cone 27.94 --cone-length 16 --tip-angle 70 -o my50.stl
    python tube_stand.py --od-top 17.37 --od-cone 15.75 --cone-length 22.48 --tip-od 3.18 -o my15.stl
    # or just the volume (standard Falcon dimensions); anything can still be changed
    python tube_stand.py --volume 50                      # -> tube_stand_50mL.stl
    python tube_stand.py --volume 15 --set base_d=80 -o wide15.stl
    python tube_stand.py --volume 50 --cone-length 18     # volume preset + your own measurement
    python tube_stand.py --volume 50 --list               # show all parameters (auto values resolved)
    # optional embossed text (needs matplotlib for the font outlines)
    python tube_stand.py --volume 50 --text "My Lab"                       # inside the skirt
    python tube_stand.py --volume 50 --text "My Lab" --text-place flange   # on top of the flange

All lengths are in mm and all angles in degrees. z = 0 is the table.
Print upright (flange on the bed). The seat hangs inside the stand, so its lowest edge needs a
small support from the build plate. Everything else is self-supporting.
"""
import argparse, struct, sys
import numpy as np

# --------------------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------------------
COMMON = dict(
    # ---- tube (required: od_top, od_cone, cone_len, and tip_od or tip_angle) ----
    od_top=None,           # outer diameter near the top of the tube
    od_cone=None,          # outer diameter where the conical bottom starts
    cone_len=None,         # length of the conical bottom
    tip_od=None,           # diameter at the end of the cone (used if set) ...
    tip_angle=None,        # ... or the full included angle of the cone
    # ---- design values; None = derived from the tube by the rules in resolve() ----
    # collar
    collar_clear=0.33,     # collar inner radius = tube radius at cone start + this
    collar_wall=1.75,      # collar wall thickness
    chamfer_in=0.5,        # inner chamfer at collar top (lead-in for the tube)
    chamfer_out=0.3,       # outer chamfer at collar top
    rib_h=0.5,             # rib height (radial); 0 = no ribs
    rib_w=1.5,             # rib width (tangential)
    rib_angles=(-135, -45, 45, 135),  # front opening is centred at -90 deg
    rib_bottom_dz=1.5,     # ribs start this far above the seat/collar junction
    rib_top_gap=2.2,       # ribs end this far below the collar top
    # seat
    seat_margin=4.0,       # seat half-angle = tube cone half-angle + this (0 = same angle as the tube)
    seat_half_angle=None,  # auto: tube half-angle + seat_margin
    lip_frac=0.54,         # seat lip radius as a fraction of the tube radius at cone start
    lip_z=None,            # auto: height where the tube radius equals the lip radius
    tip_clear=0.5,         # gap between tube tip and table
    seat_t=1.9,            # seat wall thickness (normal to the cone)
    # overall size
    height=None,           # auto: seat/collar junction + collar_len
    collar_len=None,       # auto: 15 + 0.11 * od_top
    base_d=None,           # auto: 55 + 0.85 * od_top
    # skirt / flange
    skirt_angle=55.0,      # skirt slope from horizontal
    skirt_t=2.3,           # skirt wall thickness (horizontal)
    skirt_join_dz=0.7,     # skirt outer line meets the collar this far above the seat junction
    outer_fillet=None,     # auto: 0.17 * od_top
    flange_t=1.8,          # flange thickness at the rim
    flange_top_z=4.5,      # height where the flange top meets the skirt
    # front opening
    open_angle=68.5,       # wedge angle through the collar and seat
    slot_width=None,       # auto: 0.5 * od_top + 2.3 (slot through skirt and flange)
    # stacking
    stack_clear=0.25,      # vertical clearance between collar top chamfer and seat underside
    n_tabs=5, tab_w=2.5, tab_w_key=4.0,
    tab_h=None,            # auto: 0.5 + 0.017 * od_top, limited to 0.8-1.0
    pocket_extra_h=0.3,    # pocket depth = tab_h + this
    pocket_clear_t=0.35,   # pocket tangential clearance per side
    pocket_clear_r=0.2,    # pocket radial clearance (outer wall)
    landing_z=None,        # auto: as high as possible while keeping min_wall around the pockets
    min_wall=1.5,          # target minimum wall around the landing/pockets (used by auto landing_z)
    # mesh
    n_seg=720,             # angular segments over the stand's arc (excluding the opening)
    # optional embossed text (--text); needs matplotlib
    text='',               # '' = no text
    text_place='inner',    # 'inner' = inside of the skirt (subtle), 'flange' = top of the flange
    text_size=4.0,         # font size in mm (roughly the height of a capital letter + descender)
    text_h=0.5,            # emboss height
    text_z=4.0,            # inner: height of the text centre on the skirt
    text_r=None,           # flange: radius of the text centre (None = middle of the flange top)
    text_angle=90.0,       # centre of the text arc (90 = opposite the front opening)
    text_font='DejaVu Sans:bold',  # 'family:weight'; DejaVu Sans ships with matplotlib
)

PRESETS = {
    # Corning Falcon 352070 / 352098 drawing: OD 29.72 top / 27.94 at cone start,
    # cone length 16.0 mm, 70 deg tip
    'falcon50': dict(od_top=29.72, od_cone=27.94, cone_len=16.0, tip_angle=70.0),
    # Corning Falcon 352096 drawing: OD 17.37 top / 15.75 at cone start,
    # cone length 22.48 mm, tip OD 3.18 mm
    'falcon15': dict(od_top=17.37, od_cone=15.75, cone_len=22.48, tip_od=3.18),
}
VOLUMES = {50: 'falcon50', 15: 'falcon15'}   # --volume shortcut
AUTO_KEYS = ('seat_half_angle', 'lip_z', 'height', 'collar_len', 'base_d', 'outer_fillet', 'slot_width', 'tab_h', 'landing_z')

def tube_geometry(p):
    """Tube radius at cone start, tip radius, and dr/dz of the cone."""
    rc = p['od_cone'] / 2
    if p['tip_od'] is not None:
        rtip = p['tip_od'] / 2; kt = (rc - rtip) / p['cone_len']
    else:
        kt = np.tan(np.radians(p['tip_angle'] / 2)); rtip = rc - kt * p['cone_len']
    return rc, rtip, kt

def resolve(p):
    """Fill in every design value left as None, using rules fitted to the two Falcon designs."""
    od = p['od_top']; rc, rtip, kt = tube_geometry(p)
    tube_half = np.degrees(np.arctan(kt))
    if p['seat_half_angle'] is None: p['seat_half_angle'] = tube_half + p['seat_margin']
    if p['lip_z'] is None:
        rlip = max(p['lip_frac'] * rc, rtip + 0.5)
        p['lip_z'] = p['tip_clear'] + (rlip - rtip) / kt
    if p['collar_len'] is None: p['collar_len'] = 15 + 0.11 * od
    if p['height'] is None:
        RI = rc + p['collar_clear']; RLIP = rtip + (p['lip_z'] - p['tip_clear']) * kt
        ZJ = p['lip_z'] + (RI - RLIP) / np.tan(np.radians(p['seat_half_angle']))
        p['height'] = round(ZJ + p['collar_len'], 1)
    if p['base_d'] is None:
        # rule fitted to the Falcon designs, but never less than the skirt footprint + a 10 mm flange
        RI = rc + p['collar_clear']; RO = RI + p['collar_wall']
        RLIP = rtip + (p['lip_z'] - p['tip_clear']) * kt
        ZB = p['lip_z'] + (RI - RLIP) / np.tan(np.radians(p['seat_half_angle'])) + p['skirt_join_dz']
        r_skirt = RO + (ZB - p['flange_top_z']) / np.tan(np.radians(p['skirt_angle']))
        p['base_d'] = float(max(round(55 + 0.85 * od), np.ceil(2 * (r_skirt + 10))))
    if p['outer_fillet'] is None: p['outer_fillet'] = round(0.17 * od, 1)
    if p['slot_width'] is None: p['slot_width'] = round(0.5 * od + 2.3, 1)
    if p['tab_h'] is None: p['tab_h'] = round(min(1.0, max(0.8, 0.5 + 0.017 * od)), 2)
    return p

def choose_landing(p):
    """Highest landing that keeps the clearances and at least min_wall around the pockets."""
    if p['landing_z'] is not None: return p
    q = dict(p); q['landing_z'] = None
    P, tags, d = build_profile(q)
    zmax = d['ZL']; best = (-1, zmax)
    for z in np.arange(zmax, max(zmax - 3.0, d['ZLIP'] + 1.0), -0.1):   # lower at most 3 mm
        q['landing_z'] = float(z)
        P, tags, d = build_profile(q)
        Qp = P.copy(); Qp[tags['pocket'], 1] += q['tab_h'] + q['pocket_extra_h']
        w = min_wall(Qp, (d['RLIP'], d['RP'] + 3, d['ZLIP'] + 1.5, q['height'] - 2))[0]
        if w >= p['min_wall'] - 1e-6: best = (w, float(z)); break
        if w > best[0] + 0.02: best = (w, float(z))                   # lowering only if it helps
    p['landing_z'] = round(best[1], 2)
    return p

# --------------------------------------------------------------------------------------
# 2D helpers
# --------------------------------------------------------------------------------------
def poly_area(P):
    P = np.asarray(P, float)
    return 0.5 * np.sum(P[:, 0] * np.roll(P[:, 1], -1) - np.roll(P[:, 0], -1) * P[:, 1])

def fillet(prev, corner, nxt, radius, n=8):
    """Replace `corner` by a circular arc of `radius` tangent to both edges."""
    c = np.array(corner, float)
    u = np.array(prev, float) - c; u /= np.linalg.norm(u)
    v = np.array(nxt, float) - c; v /= np.linalg.norm(v)
    half = np.arccos(np.clip(u @ v, -1, 1)) / 2
    d = radius / np.tan(half)                          # tangent length
    a, b = c + u * d, c + v * d
    bis = (u + v) / np.linalg.norm(u + v)
    ctr = c + bis * radius / np.sin(half)
    a0, a1 = np.arctan2(*(a - ctr)[::-1]), np.arctan2(*(b - ctr)[::-1])
    da = (a1 - a0 + np.pi) % (2 * np.pi) - np.pi
    return [tuple(ctr + radius * np.array([np.cos(a0 + da * t), np.sin(a0 + da * t)]))
            for t in np.linspace(0, 1, n)]

def ear_clip(P):
    P = np.asarray(P, float); idx = list(range(len(P))); T = []
    cr = lambda o, a, b: (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    eps = 1e-10
    def blocks(a, b, c, k):
        A, B, C, K = P[a], P[b], P[c], P[k]
        if np.allclose(K, A) or np.allclose(K, C): return False
        c1, c2, c3 = cr(A, B, K), cr(B, C, K), cr(C, A, K)
        if c1 > eps and c2 > eps and c3 > eps: return True          # strictly inside the ear
        if abs(c3) <= eps and min(A[0], C[0]) - eps <= K[0] <= max(A[0], C[0]) + eps \
                and min(A[1], C[1]) - eps <= K[1] <= max(A[1], C[1]) + eps: return True  # on the new diagonal
        return False
    while len(idx) > 3:
        for j in range(len(idx)):
            a, b, c = idx[j-1], idx[j], idx[(j+1) % len(idx)]
            if cr(P[a], P[b], P[c]) <= eps: continue
            if any(blocks(a, b, c, k) for k in idx if k not in (a, b, c)): continue
            T.append((a, b, c)); idx.pop(j); break
        else:
            raise RuntimeError('cross-section is not a simple polygon (check parameters)')
    T.append(tuple(idx)); return T

# --------------------------------------------------------------------------------------
# Cross-section
# --------------------------------------------------------------------------------------
def build_profile(p):
    """Return (profile points CCW, dict of tagged vertex indices, derived values)."""
    tan = lambda deg: np.tan(np.radians(deg))
    rc, rtip, kt = tube_geometry(p)
    ztip = p['tip_clear']
    RI = rc + p['collar_clear']; RO = RI + p['collar_wall']
    ZT, ci, co = p['height'], p['chamfer_in'], p['chamfer_out']
    al = p['seat_half_angle']; ta = tan(al)
    ZLIP = p['lip_z']
    RLIP = rtip + (ZLIP - ztip) * kt                 # tube radius at lip height = seat inner radius
    TSh = p['seat_t'] / np.cos(np.radians(al))       # horizontal seat thickness
    ZJ = ZLIP + (RI - RLIP) / ta                     # seat inner surface meets collar inner wall
    ZB = ZJ + p['skirt_join_dz']                     # collar outer wall meets skirt outer line
    k = 1 / tan(p['skirt_angle'])                    # dr/dz of the skirt
    ro = lambda z: RO + (ZB - z) * k                 # skirt outer
    ri = lambda z: ro(z) - p['skirt_t']              # skirt inner
    ri_inv = lambda r: ZB - (r + p['skirt_t'] - RO) / k
    su_inv = lambda r: ZLIP + (r - RLIP - TSh) / ta  # seat underside z at radius r
    RB = p['base_d'] / 2

    # landing height: as high as possible while (a) the collar's inner chamfer and
    # (b) the tab's inner face both clear the seat underside of the stand above
    kt_tab = (ci + p['tab_h']) / ci
    ZL = min(su_inv(RI) + ci - p['stack_clear'],
             su_inv(RI + (ci - p['stack_clear']) / kt_tab))
    if p.get('landing_z') is not None:               # optional: lower landing = thicker seat root, taller pitch
        ZL = min(ZL, p['landing_z'])
    rstar = RLIP + TSh + (ZL - ZLIP) * ta
    RP = RO + p['pocket_clear_r']

    tags = {}
    pts = []
    def add(pt, *tg):
        for t in tg: tags.setdefault(t, []).append(len(pts))
        pts.append((float(pt[0]), float(pt[1])))

    # outer contour, CCW starting at the flange rim
    add((RB, 0)); add((RB, p['flange_t'])); add((ro(p['flange_top_z']), p['flange_top_z']))
    # skirt outer -> fillet -> collar outer
    if p['outer_fillet'] > 0:
        f = fillet((ro(p['flange_top_z']), p['flange_top_z']), (RO, ZB), (RO, ZT - co), p['outer_fillet'])
        if np.hypot(*(np.array(f[0]) - (RO, ZB))) >= min(np.hypot(ro(p['flange_top_z']) - RO, p['flange_top_z'] - ZB),
                                                        ZT - co - ZB) - 0.1:
            sys.exit('outer_fillet too large for this geometry (or height too small)')
    else:
        f = [(RO, ZB)]
    for q in f: add(q)
    add((RO, ZT - co), 'tab')
    add((RO - co, ZT), 'tab'); add((RI + ci, ZT), 'tab'); add((RI, ZT - ci))
    add((RI, ZT - p['rib_top_gap']), 'rib'); add((RI, ZJ + p['rib_bottom_dz']), 'rib'); add((RI, ZJ))
    # seat inner surface down to the lip, lip, seat underside up to the landing
    add((RLIP, ZLIP)); add((RLIP + TSh, ZLIP))
    add((rstar, ZL))
    r_pi = max(rstar + 0.04, RI + 0.05)              # pocket inner edge
    if r_pi > rstar + 0.04: add((r_pi - 0.04, ZL))
    add((r_pi, ZL), 'pocket')
    rz = ri(ZL)                                      # where the skirt inner surface crosses the landing height
    rim = max(1.0, p['min_wall'] + 0.1)              # solid rim outside the pocket wall
    if rz > RP + rim:      # skirt inner is far out: flat landing, then 45 deg up to the skirt
        add((RP, ZL), 'pocket'); add((RP + 0.05, ZL)); add((RP + rim, ZL))
        rch = (ZB + (RO - p['skirt_t']) / k - ZL + RP + rim) / (1 + 1 / k)
        add((rch, ZL + rch - RP - rim))
    elif rz > RP + 0.05:   # landing ends on the skirt inner surface, outside the pocket
        add((RP, ZL), 'pocket'); add((RP + 0.05, ZL)); add((rz, ZL))
    else:                  # skirt inner drops below the landing inside the pocket radius
        add((rz, ZL), 'pocket'); add((RP, ri_inv(RP)), 'pocket'); add((RP + 0.05, ri_inv(RP + 0.05)))
    add((ri(0), 0))
    P = np.array(pts)
    assert poly_area(P) > 0, 'profile orientation'
    d = dict(RI=RI, RO=RO, ZJ=ZJ, ZL=ZL, RLIP=RLIP, ZLIP=ZLIP, rstar=rstar, RP=RP,
             tube_r_cone=rc, tube_tip_r=rtip, tube_tip_z=ztip, tube_k=kt,
             pitch=ZT - ZL, foot_inner=ri(0),
             flange=(ro(p['flange_top_z']), p['flange_top_z'], RB, p['flange_t']), slot_half_w=p['slot_width'] / 2)
    return P, tags, d

def validate(p):
    """Catch parameter combinations that cannot produce a valid stand."""
    err = []
    for k in ('od_top', 'od_cone', 'cone_len'):
        if p[k] is None: err.append(f'tube dimension {k} is required')
    if p['tip_od'] is None and p['tip_angle'] is None: err.append('give the tube tip as tip_od or tip_angle')
    if err: sys.exit('invalid parameters: ' + '; '.join(err))
    if p['od_cone'] > p['od_top']: err.append('od_cone should not be larger than od_top')
    if p['tip_od'] is not None and not 0 <= p['tip_od'] < p['od_cone']: err.append('tip_od must be smaller than od_cone')
    if p['tip_od'] is None and not 0 < p['tip_angle'] < 180: err.append('tip_angle must be between 0 and 180')
    if p['tip_od'] is None and np.tan(np.radians(p['tip_angle'] / 2)) * p['cone_len'] >= p['od_cone'] / 2:
        err.append('tip_angle and cone_len give a cone that ends before cone_len')
    for k in ('chamfer_in', 'chamfer_out', 'collar_wall', 'seat_t', 'skirt_t', 'flange_t', 'cone_len'):
        if p[k] <= 0: err.append(f'{k} must be > 0')
    for k in ('rib_h', 'tab_h', 'outer_fillet', 'pocket_extra_h', 'pocket_clear_t', 'pocket_clear_r'):
        if p[k] is not None and p[k] < 0: err.append(f'{k} must be >= 0')
    if p['n_tabs'] < 0 or p['n_seg'] < 90: err.append('n_tabs must be >= 0 and n_seg >= 90')
    if not 0 < p['open_angle'] < 180: err.append('open_angle must be between 0 and 180')
    if not 0 < p['skirt_angle'] < 90: err.append('skirt_angle must be between 0 and 90')
    if p['seat_margin'] < 0: err.append('seat_margin must be >= 0')
    if err: sys.exit('invalid parameters: ' + '; '.join(err))

def check_profile(P, p, d):
    """Geometric sanity checks on the cross-section; returns a list of problems."""
    probs = []
    n = len(P)
    cr = lambda o, a, b: (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    for i in range(n):
        if np.hypot(*(P[(i+1) % n] - P[i])) < 1e-6: probs.append(f'duplicate point {np.round(P[i], 2)}')
        for j in range(i + 2, n):
            if (j + 1) % n == i: continue
            a, b, c, e = P[i], P[(i+1) % n], P[j], P[(j+1) % n]
            if cr(a, b, c) * cr(a, b, e) < 0 and cr(c, e, a) * cr(c, e, b) < 0:
                probs.append(f'cross-section edges {i} and {j} intersect')
    if not (0 < d['ZJ'] < p['height'] - p['chamfer_in'] - 1): probs.append('seat meets the collar above its top: increase height')
    if d['ZJ'] + p['rib_bottom_dz'] >= p['height'] - p['rib_top_gap']: probs.append('no room for ribs: reduce rib_bottom_dz/rib_top_gap')
    if not 0 < p['seat_half_angle'] < 90: probs.append('seat_half_angle must be between 0 and 90')
    if p['seat_half_angle'] < np.degrees(np.arctan(d['tube_k'])) - 1e-9:
        probs.append('seat_half_angle is smaller than the tube cone: the tube would wedge at the top of the seat')
    if d['RLIP'] <= 0: probs.append('seat lip radius <= 0: raise lip_z or change tube tip parameters')
    if d['ZL'] <= d['ZLIP']: probs.append('landing below the seat lip: check landing_z / clearances')
    if p['base_d'] / 2 <= d['flange'][0] + 1: probs.append('base_d too small for the skirt')
    return probs

# --------------------------------------------------------------------------------------
# Revolve
# --------------------------------------------------------------------------------------
def tab_layout(p):
    half = p['open_angle'] / 2
    n = p['n_tabs']
    centres = [-90 + half + (360 - 2 * half) * (i + 0.5) / n for i in range(n)]
    widths = [p['tab_w']] * n
    if n:   # the tab closest to the back (90 deg) is the wider key tab
        widths[int(np.argmin([abs(((c - 90 + 180) % 360) - 180) for c in centres]))] = p['tab_w_key']
    return centres, widths

def orientation_check(p, d, step=0.25):
    """Rotations (deg) other than 0 at which every tab of the lower stand fits into a pocket
    or the front opening of the upper stand, i.e. the stands could nest in the wrong orientation."""
    centres, widths = tab_layout(p)
    if not centres: return []
    R = d['RO'] - p['chamfer_out']                   # outer edge of the tab top (smallest angular margin)
    tabs = [(c, np.degrees(w / 2 / R)) for c, w in zip(centres, widths)]
    pockets = [(c, np.degrees((w / 2 + p['pocket_clear_t']) / R)) for c, w in zip(centres, widths)]
    half_open = p['open_angle'] / 2
    wrap = lambda x: (x + 180) % 360 - 180
    def fits(delta):
        for c, hw in tabs:
            a = wrap(c - delta)                      # tab position in the upper stand's frame
            in_pocket = any(abs(wrap(a - pc)) + hw <= ph + 1e-9 for pc, ph in pockets)
            in_open = abs(wrap(a + 90)) + hw <= half_open
            if not (in_pocket or in_open): return False
        return True
    deltas = np.arange(-180, 180, step)
    ok = np.array([fits(x) for x in deltas])
    # the contiguous range around 0 deg is the intended fit (play within the pocket clearance)
    i0 = int(np.argmin(np.abs(deltas))); lo = hi = i0
    while lo > 0 and ok[lo - 1]: lo -= 1
    while hi < len(ok) - 1 and ok[hi + 1]: hi += 1
    ok[lo:hi + 1] = False
    return [round(float(x), 2) for x in deltas[ok]]

def angular_zone(phi, centre_deg, half_rad):
    return np.abs((phi - np.radians(centre_deg) + np.pi) % (2 * np.pi) - np.pi) <= half_rad

def revolve(P, tags, p, d):
    P = np.asarray(P, float); n = len(P); N = p['n_seg']
    half = np.radians(p['open_angle'] / 2)
    Rref = p['slot_width'] / (2 * np.sin(half))      # wedge inside Rref, constant-width slot outside
    h = np.arcsin(np.clip(p['slot_width'] / (2 * np.maximum(P[:, 0], Rref)), -1, 1))
    phi = (-np.pi / 2 + h)[None, :] + (np.arange(N + 1)[:, None] / N) * (2 * np.pi - 2 * h)[None, :]
    r = np.repeat(P[None, :, 0], N + 1, 0).copy()
    z = np.repeat(P[None, :, 1], N + 1, 0).copy()
    rib_hw = (p['rib_w'] / 2) / d['RI']
    for i in tags.get('rib', []):
        dist = np.min([np.abs((phi[:, i] - np.radians(a) + np.pi) % (2 * np.pi) - np.pi) for a in np.atleast_1d(p['rib_angles'])], 0)
        r[:, i] -= p['rib_h'] * np.where(dist < rib_hw, 0.5 * (1 + np.cos(np.pi * dist / rib_hw)), 0)
    centres, widths = tab_layout(p)
    for c, w in zip(centres, widths):
        for i in tags.get('tab', []):
            z[:, i] += p['tab_h'] * angular_zone(phi[:, i], c, (w / 2) / P[i, 0])
        for i in tags.get('pocket', []):
            z[:, i] += (p['tab_h'] + p['pocket_extra_h']) * angular_zone(phi[:, i], c, (w / 2 + p['pocket_clear_t']) / P[i, 0])
    V = np.stack([r * np.cos(phi), r * np.sin(phi), z], -1).reshape(-1, 3)
    kk, ii = np.meshgrid(np.arange(N), np.arange(n), indexing='ij')
    a = (kk * n + ii).ravel(); b = (kk * n + (ii + 1) % n).ravel()
    c_ = ((kk + 1) * n + (ii + 1) % n).ravel(); d_ = ((kk + 1) * n + ii).ravel()
    F = [np.stack([a, b, c_], 1), np.stack([a, c_, d_], 1)]
    cap = np.array(ear_clip(P))
    F.append(cap[:, [0, 2, 1]]); F.append(cap + N * n)
    F = np.concatenate(F)
    T = V[F]
    vol = np.einsum('ij,ij->i', T[:, 0], np.cross(T[:, 1], T[:, 2])).sum() / 6
    if vol < 0: F = F[:, ::-1]; T = V[F]; vol = -vol
    return T, F, vol



# --------------------------------------------------------------------------------------
# Optional embossed text
# --------------------------------------------------------------------------------------
def _pip(pt, poly):
    x, y = pt; inside = False; n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]; x1, y1 = poly[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0): inside = not inside
    return inside

def _seg_cross(a, b, c, d):
    cr = lambda o, p, q: (p[0]-o[0])*(q[1]-o[1]) - (p[1]-o[1])*(q[0]-o[0])
    return cr(a, b, c) * cr(a, b, d) < 0 and cr(c, d, a) * cr(c, d, b) < 0

def _merge_holes(outer, holes):
    """Bridge the holes of a glyph (e.g. inside 'o') into its outline so it can be ear-clipped."""
    poly = [tuple(q) for q in outer]
    for hole in sorted(holes, key=lambda h: -max(q[0] for q in h)):
        hole = [tuple(q) for q in hole]; mi = max(range(len(hole)), key=lambda i: hole[i][0]); M = hole[mi]
        edges = [(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))]
        for h in holes: edges += [(tuple(h[i]), tuple(h[(i + 1) % len(h)])) for i in range(len(h))]
        counts = {}
        for q in poly: counts[q] = counts.get(q, 0) + 1
        for vi, V in sorted(enumerate(poly), key=lambda t: (t[1][0] - M[0])**2 + (t[1][1] - M[1])**2):
            if counts[V] > 1: continue                 # never reuse an earlier bridge point
            if all(not _seg_cross(M, V, e0, e1) for e0, e1 in edges if V not in (e0, e1) and M not in (e0, e1)): break
        else:
            raise RuntimeError('could not bridge a glyph hole')
        poly = poly[:vi + 1] + hole[mi:] + hole[:mi + 1] + [V] + poly[vi + 1:]
    return poly

def glyph_outlines(text, size, font):
    """Text outlines (mm) from matplotlib's TextPath: list of (outer, [holes])."""
    try:
        from matplotlib.textpath import TextPath
        from matplotlib.font_manager import FontProperties
        from matplotlib.path import Path as MPath
    except ImportError:
        sys.exit('--text needs matplotlib (pip install matplotlib)')
    fam, _, wt = font.partition(':')
    prop = FontProperties(family=fam, weight=wt or 'normal')
    # refuse silently-substituted fonts and missing characters (they would print as boxes)
    import matplotlib.font_manager as fm
    from matplotlib.ft2font import FT2Font
    try:
        path = fm.findfont(prop, fallback_to_default=False)
    except Exception:
        sys.exit(f'font "{fam}" not found. Installed families include: '
                 + ', '.join(sorted({f.name for f in fm.fontManager.ttflist})[:15]) + ' ...')
    ft = FT2Font(path)
    missing = sorted({ch for ch in text if not ch.isspace() and ft.get_char_index(ord(ch)) == 0})
    if missing:
        sys.exit(f'font "{fam}" has no glyphs for: {"".join(missing)}. Choose a font that has them, '
                 f'e.g. --set "text_font=Noto Sans CJK JP:bold" for Japanese (fonts must be installed).')
    tp = TextPath((0, 0), text, size=size, prop=prop)
    polys, cur = [], []
    for seg, code in tp.iter_bezier():                 # flatten curves finely
        if code == MPath.MOVETO:
            if len(cur) > 3: polys.append(np.array(cur))
            cur = [tuple(seg.control_points[0])]; continue
        if code == MPath.CLOSEPOLY: continue
        ts = np.linspace(0, 1, 2 if seg.degree == 1 else 9)[1:]
        cur += [tuple(q) for q in np.atleast_2d(seg(ts))]
    if len(cur) > 3: polys.append(np.array(cur))
    polys = [q[:-1] if np.allclose(q[0], q[-1]) else q for q in polys]
    polys = [q[np.r_[True, np.any(np.abs(np.diff(q, axis=0)) > 1e-6, axis=1)]] for q in polys]
    if not polys: sys.exit('text produced no outlines')
    # filled contours vs holes by winding direction (fonts use the non-zero rule: holes run the
    # other way). Overlapping filled contours (common in CJK fonts) become separate overlapping shells.
    # Decide per contour, from the largest down: a contour inside nothing is filled; a contour
    # inside another one has the same role as its container if it winds the same way, else the
    # opposite role. Works for both winding conventions, for fallback glyphs from other fonts,
    # and for overlapping strokes (CJK), which become separate overlapping shells.
    areas = [poly_area(q) for q in polys]
    order = sorted(range(len(polys)), key=lambda i: -abs(areas[i]))
    inside = lambda i, j: all(_pip(q, polys[j]) for q in polys[i][::max(1, len(polys[i]) // 8)])
    filled_role, container = {}, {}
    for k, i in enumerate(order):
        cands = [j for j in order[:k] if abs(areas[j]) > abs(areas[i]) and inside(i, j)]
        if not cands: filled_role[i] = True; continue
        c = min(cands, key=lambda j: abs(areas[j])); container[i] = c
        filled_role[i] = filled_role[c] if np.sign(areas[i]) == np.sign(areas[c]) else not filled_role[c]
    polys = [q if filled_role[i] == (areas[i] > 0) else q[::-1] for i, q in enumerate(polys)]  # filled CCW, holes CW
    groups = {i: [] for i in range(len(polys)) if filled_role[i]}
    for i in range(len(polys)):
        if not filled_role[i] and i in container and filled_role[container[i]]: groups[container[i]].append(i)
    allp = np.concatenate(polys)
    return [(polys[o], [polys[h] for h in hs]) for o, hs in groups.items()], allp

def text_triangles(P, p, d):
    """Embossed text as closed shells that sink 0.4 mm into the stand (the slicer merges them).
    Returns (triangles, info dict)."""
    glyphs, allp = glyph_outlines(p['text'], p['text_size'], p['text_font'])
    uc = (allp[:, 0].min() + allp[:, 0].max()) / 2; vc = (allp[:, 1].min() + allp[:, 1].max()) / 2
    width = allp[:, 0].max() - allp[:, 0].min(); tall = allp[:, 1].max() - allp[:, 1].min()
    sink = 0.4
    if p['text_place'] == 'inner':
        (r1, z1), (r0, z0) = P[-2], P[-1]               # skirt inner surface, foot -> up
        t = np.array([r1 - r0, z1 - z0]); t /= np.linalg.norm(t)     # up the slope
        n = np.array([-t[1], t[0]])
        if n[1] > 0: n = -n                                          # into the open cavity
        base = np.array([r0, z0]) + t * ((p['text_z'] - z0) / t[1])
        def to_rz(u, v, off):
            rz = base[None, :] + (v - vc)[:, None] * t[None, :] + off * n[None, :]
            return rz[:, 0], rz[:, 1]
        Rc = base[0]
    elif p['text_place'] == 'flange':
        r_in, z_in, RB, z_rim = d['flange']
        Rc = p['text_r'] or (r_in + RB) / 2
        ztop = lambda r: z_rim + (RB - r) * (z_in - z_rim) / (RB - r_in)
        def to_rz(u, v, off):
            r = Rc + (v - vc); return r, ztop(r) + off
    else:
        sys.exit("text_place must be 'inner' or 'flange'")
    def to3d(uv, off):
        r, z = to_rz(uv[:, 0], uv[:, 1], off)
        th = np.radians(p['text_angle']) - (uv[:, 0] - uc) / Rc   # reads left to right, upright
        return np.stack([r * np.cos(th), r * np.sin(th), z], -1)
    tris = []
    for outer, holes in glyphs:
        merged = np.array(_merge_holes(outer, holes)); cap = np.array(ear_clip(merged))
        top, bot = to3d(merged, p['text_h']), to3d(merged, -sink)
        tris += [top[cap], bot[cap][:, ::-1]]
        for ring in [outer] + holes:
            b_, t_ = to3d(ring, -sink), to3d(ring, p['text_h'])
            b2, t2 = np.roll(b_, -1, 0), np.roll(t_, -1, 0)
            tris += [np.stack([b_, b2, t2], 1), np.stack([b_, t2, t_], 1)]
    T = np.concatenate(tris)
    if np.einsum('ij,ij->i', T[:, 0], np.cross(T[:, 1], T[:, 2])).sum() < 0: T = T[:, ::-1]
    # where the text sits, for the checks
    span = np.degrees(width / Rc)
    rr = np.hypot(T[..., 0], T[..., 1])
    info = dict(arc=span, r=(rr.min(), rr.max()), z=(T[..., 2].min(), T[..., 2].max()), Rc=Rc, tall=tall)
    return T, info

def check_text(T, info, P, p, d, pitch):
    """Problems with the text placement (list of strings)."""
    probs = []
    # 1. clear of the front opening (with 5 deg margin)
    half_open_here = np.degrees(np.arcsin(min(1, p['slot_width'] / (2 * info['Rc'])))) if info['Rc'] > d['RO'] \
        else p['open_angle'] / 2
    free = 360 - 2 * (half_open_here + 5)
    a0 = ((p['text_angle'] + 90) % 360)                # angular distance of the text centre from the opening
    room = 2 * min(a0, 360 - a0) - 2 * (half_open_here + 5)
    if info['arc'] > min(free, room):
        probs.append(f'text spans {info["arc"]:.0f} deg of arc but only {min(free, room):.0f} deg is free of the '
                     f'front opening: shorten the text or reduce text_size')
    # 2. stays on its surface
    if p['text_place'] == 'inner':
        (r1, z1), (r0, z0) = P[-2], P[-1]
        if info['z'][0] < 0.8 or info['z'][1] > min(z1, d['ZLIP']) - 0.3:
            probs.append(f'text (z {info["z"][0]:.1f}-{info["z"][1]:.1f} mm) does not fit on the inside of the skirt '
                         f'(about z 0.8-{min(z1, d["ZLIP"]) - 0.3:.1f} mm): change text_z or text_size')
        # 3. stacked stand below must not touch the text (its collar comes up inside the skirt)
        lower = P.copy(); lower[:, 1] -= pitch
        A, B = lower, np.roll(lower, -1, 0); r_lower = 0.0
        for zz in np.linspace(info['z'][0] - 1, info['z'][1] + 1, 25):
            m = (np.minimum(A[:, 1], B[:, 1]) <= zz) & (np.maximum(A[:, 1], B[:, 1]) > zz)
            if m.any():
                x = A[m, 0] + (zz - A[m, 1]) / (B[m, 1] - A[m, 1]) * (B[m, 0] - A[m, 0])
                r_lower = max(r_lower, x.max())
        if r_lower > info['r'][0] - 0.5:
            probs.append('the stand below (when stacked) comes too close to the text: lower text_z')
    else:
        r_in, z_in, RB, z_rim = d['flange']
        if info['r'][0] < r_in + 0.5 or info['r'][1] > RB - 0.5:
            probs.append(f'text (r {info["r"][0]:.1f}-{info["r"][1]:.1f} mm) does not fit on the flange top '
                         f'(r {r_in:.1f}-{RB:.1f} mm): change text_r or text_size')
    return probs

# --------------------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------------------
def check_manifold(F):
    E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    key = E[:, 0].astype(np.int64) * (F.max() + 1) + E[:, 1]
    rkey = E[:, 1].astype(np.int64) * (F.max() + 1) + E[:, 0]
    u, cnt = np.unique(key, return_counts=True)
    return bool((cnt == 1).all() and np.isin(rkey, u).all())

def min_wall(P, region, skip=0.3, step=0.05):
    """Smallest inward-normal ray length from boundary points inside region=(r0,r1,z0,z1)."""
    P = np.asarray(P, float); n = len(P); E0, E1 = P, np.roll(P, -1, 0); D = E1 - E0
    best = (np.inf, None)
    for i in range(n):
        a, b = P[i], P[(i + 1) % n]; L = np.hypot(*(b - a))
        if L < 1e-9: continue
        t = (b - a) / L; nin = np.array([-t[1], t[0]])
        for s in np.arange(step / 2, L, step):
            q = a + t * s
            if not (region[0] <= q[0] <= region[1] and region[2] <= q[1] <= region[3]): continue
            if np.min(np.hypot(*(P - q).T)) < skip: continue
            den = nin[0] * D[:, 1] - nin[1] * D[:, 0]; ok = np.abs(den) > 1e-12
            w = E0 - q
            u = np.where(ok, (w[:, 0] * D[:, 1] - w[:, 1] * D[:, 0]) / np.where(ok, den, 1), np.inf)
            v = np.where(ok, (w[:, 0] * nin[1] - w[:, 1] * nin[0]) / np.where(ok, den, 1), -1)
            m = ok & (u > 1e-4) & (v >= 0) & (v <= 1); m[i] = False
            if m.any() and u[m].min() < best[0]: best = (u[m].min(), tuple(np.round(q, 2)))
    return best

def raster(P, dz=0.02, dr=0.02, H=None):
    P = np.asarray(P, float); H = H or P[:, 1].max() + 2
    zs = np.arange(0, H, dz) + dz / 2; rs = np.arange(0, P[:, 0].max() + 1, dr) + dr / 2
    M = np.zeros((len(zs), len(rs)), bool); A, B = P, np.roll(P, -1, 0)
    for iz, zz in enumerate(zs):
        m = (np.minimum(A[:, 1], B[:, 1]) < zz) & (np.maximum(A[:, 1], B[:, 1]) >= zz)
        x = np.sort(A[m, 0] + (zz - A[m, 1]) / (B[m, 1] - A[m, 1]) * (B[m, 0] - A[m, 0]))
        for x0, x1 in zip(x[0::2], x[1::2]): M[iz, (rs > x0) & (rs < x1)] = True
    return M

def min_pitch(lower, upper, dz=0.02):
    H = max(lower[:, 1].max(), upper[:, 1].max()) + 2
    A, B = raster(lower, dz=dz, H=H), raster(upper, dz=dz, H=H)
    w = min(A.shape[1], B.shape[1]); A, B = A[:, :w], B[:, :w]
    for s in range(1, len(A)):
        if not (B[:len(A) - s] & A[s:]).any(): return s * dz
    return np.nan

def stacking_report(P, tags, p, d):
    def lifted(tag, dzv):
        Q = P.copy(); Q[tags[tag], 1] += dzv; return Q
    ribbed = P.copy(); ribbed[tags['rib'], 0] -= p['rib_h']
    tabbed = lifted('tab', p['tab_h']); pocketed = lifted('pocket', p['tab_h'] + p['pocket_extra_h'])
    res = {'plain': min_pitch(P, P), 'at ribs': min_pitch(ribbed, P), 'tab in pocket': min_pitch(tabbed, pocketed),
           'tab vs. no pocket (misaligned)': min_pitch(tabbed, P)}
    return res

# --------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------
def write_stl(path, T, name='tube_stand'):
    T = np.asarray(T, np.float32)
    nrm = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]); L = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = nrm / np.where(L == 0, 1, L)
    rec = np.zeros(len(T), np.dtype([('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')]))
    rec['n'] = nrm; rec['v'] = T
    with open(path, 'wb') as f:
        f.write(name.encode()[:80].ljust(80, b' ')); f.write(struct.pack('<I', len(T))); f.write(rec.tobytes())

def parse_value(s):
    if s.strip().lower() in ('none', 'null', ''): return None
    try: return tuple(float(x) for x in s.split(',')) if ',' in s else float(s)
    except ValueError: sys.exit(f'cannot parse value: {s}')

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_argument_group('tube (required unless --preset is given)')
    g.add_argument('--od-top', type=float, help='outer diameter near the top of the tube (mm)')
    g.add_argument('--od-cone', type=float, help='outer diameter where the cone starts (mm)')
    g.add_argument('--cone-length', type=float, help='length of the conical bottom (mm)')
    g.add_argument('--tip-angle', type=float, help='full included angle of the cone (deg)')
    g.add_argument('--tip-od', type=float, help='diameter at the end of the cone (mm), instead of --tip-angle')
    ap.add_argument('--volume', type=int, choices=sorted(VOLUMES), help='standard tube by volume in mL (Falcon dimensions)')
    ap.add_argument('--preset', choices=sorted(PRESETS), help='start from a named tube')
    ap.add_argument('--set', action='append', default=[], metavar='KEY=VALUE', help='override any parameter')
    ap.add_argument('-o', '--out', default=None, help='output STL path (default: tube_stand.stl or <preset>.stl)')
    ap.add_argument('--profile-csv', default=None, help='also write the 2D cross-section (r,z) as CSV')
    ap.add_argument('--no-check', action='store_true', help='skip the (slower) wall/stacking checks')
    ap.add_argument('--list', action='store_true', help='print all parameters (auto values resolved) and exit')
    ap.add_argument('--text', default=None, help='emboss this text (needs matplotlib)')
    ap.add_argument('--text-place', choices=('inner', 'flange'), default=None,
                    help="where to put the text: inside of the skirt (default) or top of the flange")
    a = ap.parse_args(argv)
    p = dict(COMMON)
    if a.volume and a.preset: sys.exit('give either --volume or --preset')
    preset = a.preset or (VOLUMES[a.volume] if a.volume else None)
    if preset: p.update(PRESETS[preset])
    for k_, v_ in (('od_top', a.od_top), ('od_cone', a.od_cone), ('cone_len', a.cone_length)):
        if v_ is not None: p[k_] = v_
    if a.tip_od is not None: p['tip_od'], p['tip_angle'] = a.tip_od, None
    if a.tip_angle is not None: p['tip_angle'], p['tip_od'] = a.tip_angle, None
    if a.tip_od is not None and a.tip_angle is not None: sys.exit('give either --tip-od or --tip-angle, not both')
    for kv in a.set:
        if '=' not in kv: sys.exit(f'--set expects KEY=VALUE, got: {kv}')
        k_, v_ = kv.split('=', 1)
        if k_ not in p: sys.exit(f'unknown parameter: {k_}')
        p[k_] = v_ if isinstance(COMMON[k_], str) else parse_value(v_)   # text parameters stay strings
    if a.text is not None: p['text'] = a.text
    if a.text_place is not None: p['text_place'] = a.text_place
    if p['text'] is None: p['text'] = ''
    p['text'] = str(p['text'])
    for key in ('n_tabs', 'n_seg'): p[key] = int(p[key])
    validate(p)
    resolve(p)
    validate(p)                                      # again, now with the auto values filled in
    choose_landing(p)
    if a.list:
        fmt = lambda v: f'{v:.3g}' if isinstance(v, float) and abs(v) < 1 else (f'{v:.2f}'.rstrip('0').rstrip('.') if isinstance(v, float) else v)
        for k_ in COMMON: print(f'{k_:16s} {fmt(p[k_])}' + ('   (auto)' if k_ in AUTO_KEYS and COMMON[k_] is None and
                                                       not any(s_.startswith(k_ + '=') for s_ in a.set) else ''))
        return
    out = a.out or (f'tube_stand_{a.volume}mL.stl' if a.volume else f'{preset}.stl' if preset else 'tube_stand.stl')

    P, tags, d = build_profile(p)
    probs = check_profile(P, p, d)
    if probs: sys.exit('cannot build this stand:\n  - ' + '\n  - '.join(probs))
    T, F, vol = revolve(P, tags, p, d)
    Ttxt, tinfo = text_triangles(P, p, d) if p['text'] else (np.zeros((0, 3, 3)), None)
    write_stl(out, np.concatenate([T, Ttxt]) if len(Ttxt) else T, 'tube stand')
    if a.profile_csv: np.savetxt(a.profile_csv, P, delimiter=',', header='r,z', comments='', fmt='%.4f')

    print(f'{out}: {len(T)} triangles, volume {vol/1000:.1f} cm3 (~{vol/1000*1.27:.0f} g PETG)')
    print(f'  height {p["height"]:.1f} mm, base {p["base_d"]:.1f} mm, collar ID {2*d["RI"]:.2f} mm '
          f'(ribs {2*(d["RI"]-p["rib_h"]):.2f} mm)')
    print(f'  seat: half-angle {p["seat_half_angle"]:.1f} deg (tube {np.degrees(np.arctan(d["tube_k"])):.1f}), '
          f'lip r={d["RLIP"]:.2f} at z={d["ZLIP"]:.2f}, tube tip at z={d["tube_tip_z"]:.2f}; landing z={d["ZL"]:.2f}')
    print(f'  closed manifold: {check_manifold(F)}')
    if tinfo:
        print(f'  text "{p["text"]}" ({p["text_place"]}): {tinfo["arc"]:.0f} deg of arc, '
              f'r {tinfo["r"][0]:.1f}-{tinfo["r"][1]:.1f} mm, z {tinfo["z"][0]:.1f}-{tinfo["z"][1]:.1f} mm, '
              f'emboss {p["text_h"]} mm (separate shells, merged by the slicer)')
    nominal = None
    if not a.no_check:
        reg = (d['RLIP'], d['RP'] + 3, d['ZLIP'] + 1.5, p['height'] - 2)   # skip the seat lip's sharp edge
        Qp = P.copy(); Qp[tags['pocket'], 1] += p['tab_h'] + p['pocket_extra_h']
        w0, w1 = min_wall(P, reg), min_wall(Qp, reg)
        print(f'  min wall around landing: {w0[0]:.2f} mm (at pockets {w1[0]:.2f} mm)')
        if min(w0[0], w1[0]) < p['min_wall'] - 0.01:
            wr, wz = (w1[1] if w1[0] < w0[0] else w0[1])
            print(f'  WARNING: wall below min_wall={p["min_wall"]} mm near r={wr:.1f}, z={wz:.1f} mm')
        rep = stacking_report(P, tags, p, d)
        nominal = max(rep['plain'], rep['at ribs'], rep['tab in pocket'])
        top = p['tab_h'] if p['n_tabs'] else 0
        print(f'  stack pitch {nominal:.2f} mm (design {d["pitch"]:.2f}); '
              f'5-stack height {p["height"] + 4*nominal + top:.1f} mm')
        if nominal > d['pitch'] + 0.05:
            print('  WARNING: something other than the collar top touches first when stacked')
        if p['n_tabs']:
            if rep['tab vs. no pocket (misaligned)'] <= nominal + 1e-6:
                print('  WARNING: a misplaced tab does not lift the stand above (increase tab_h)')
            wrong = orientation_check(p, d)
            if wrong:
                print(f'  WARNING: stands can also nest when rotated by {wrong[0]:.1f} deg'
                      f'{" (and others)" if len(wrong) > 1 else ""} - change tab widths/count')
            else:
                print('  orientation: unique (tabs fit only in the intended orientation)')
    if tinfo:
        for pr in check_text(Ttxt, tinfo, P, p, d, nominal or d['pitch']): print('  WARNING: ' + pr)

if __name__ == '__main__':
    main()

"""Scene 2, 00:20-00:45: off-chain verification. Measurements, H3 cell, nullifier, who checks what."""
from __future__ import annotations

import math

from tools import demo_style as S

TITLE = "Off-chain verification"
SECONDS = 25
CAPTIONS = [
    (0.3, 7.0, "Off-chain, the capture is measured: trunk diameter at breast height (DBH) and estimated biomass."),
    (7.0, 14.0, "The GPS fix becomes an H3 cell at resolution 12, about 307 m². Coordinates never go on chain."),
    (14.0, 20.5, "keccak256(cell ++ salt) gives a 32-byte spatial nullifier. While it is active, a second mint "
                 "with it reverts: NullifierInUse."),
    (20.5, 24.7, "The evidence is checked off-chain. The contract verifies no proof: it trusts the VERIFIER_ROLE "
                 "account."),
]
NARRATION = ("Off-chain, the capture is measured: trunk diameter at breast height, and estimated biomass. "
             "The GPS fix becomes an H3 cell at resolution twelve, about three hundred square metres. "
             "Coordinates never go on chain. A hash of the cell and a salt gives a thirty-two byte spatial "
             "nullifier. While it is active, a second mint with it is rejected. "
             "The evidence is checked off-chain; the contract trusts the verifier role account.")

DBH, BIOMASS = 24, 312  # the dashboard's default example capture


def _hex_grid(d, cx, cy, r, a, highlight):
    w = math.sqrt(3) * r
    for row in range(-4, 5):
        for col in range(-5, 6):
            x = cx + col * w + (w / 2 if row % 2 else 0)
            y = cy + row * 1.5 * r
            if abs(x - cx) > 290 or abs(y - cy) > 215:  # keep clear of the header and the side panels
                continue
            centre = row == 0 and col == 0
            fill = S.mix(S.BG, S.ACCENT, 0.55 * highlight) if centre else None
            S.hexagon(d, (x, y), r - 3, fill=fill, outline=S.ACCENT if centre else S.RULE,
                      width=4 if centre else 2, a=a)


def draw(img, d, t, facts):
    h3 = facts["demo_h3"]

    # measurements, always on the left
    a_m = S.ramp(t, 0.2, 0.8)
    for i, (label, value, unit) in enumerate((("DBH", DBH, "cm"), ("BIOMASS", BIOMASS, "kg"))):
        a = a_m * S.ramp(t, 0.6 + i * 0.8)
        y = 170 + i * 230
        S.box(d, (80, y, 520, y + 200), a=a)
        S.text(d, (110, y + 24), label, 26, S.MUTED, bold=True, a=a, bg=S.SURFACE)
        S.text(d, (110, y + 80), f"{value}", 84, S.TEXT, bold=True, mono=True, a=a, bg=S.SURFACE)
        S.text(d, (110 + 55 * len(str(value)) + 30, y + 118), unit, 36, S.MUTED, a=a, bg=S.SURFACE)
    S.text(d, (80, 640), "example capture · units are an off-chain", 24, S.MUTED, a=a_m)
    S.text(d, (80, 672), "convention; the contract stores uint96", 24, S.MUTED, a=a_m)

    # H3 cell
    a_h = S.ramp(t, 6.8, 0.8)
    if a_h > 0:
        _hex_grid(d, 900, 420, 50, a_h, S.ramp(t, 8.0, 1.0))
        d.ellipse((892, 412, 908, 428), fill=S.fade(S.CELO, a_h))
        S.text(d, (900, 690), f"lat {h3['lat']}  lng {h3['lng']}", 28, S.MUTED, mono=True, anchor="ma", a=a_h)
        S.text(d, (900, 734), f"H3 r{h3['resolution']} cell {h3['cell']}", 30, S.TEXT, mono=True, anchor="ma",
               a=a_h * S.ramp(t, 8.3))
        S.text(d, (900, 776), f"≈ {h3['cell_area_m2']} m²", 26, S.MUTED, anchor="ma", a=a_h * S.ramp(t, 8.3))

    # nullifier
    a_n = S.ramp(t, 13.8, 0.8)
    if a_n > 0:
        S.box(d, (1260, 170, 1840, 560), a=a_n)
        S.text(d, (1290, 196), "SPATIAL NULLIFIER", 26, S.MUTED, bold=True, a=a_n, bg=S.SURFACE)
        S.text(d, (1290, 246), "keccak256(uint64(cell) ++ salt)", 26, S.TEXT, mono=True, a=a_n, bg=S.SURFACE)
        S.text(d, (1290, 290), f'salt "{h3["salt"]}"', 26, S.MUTED, mono=True, a=a_n, bg=S.SURFACE)
        n = h3["nullifier"]
        typed = int(len(n) * S.clamp01((t - 14.5) / 2.0))
        for i in range(0, 66, 22):
            S.text(d, (1290, 350 + (i // 22) * 44), n[i:i + 22][: max(0, typed - i)], 30, S.CELO, mono=True,
                   a=a_n, bg=S.SURFACE)
        S.pill(d, (1290, 486), "32 bytes · non-zero", size=22, a=a_n * S.ramp(t, 16.8))
        S.arrow(d, (1100, 420), (1240, 380), S.ramp(t, 14.2, 0.8))

    # who checks what
    a_w = S.ramp(t, 20.3, 0.7)
    if a_w > 0:
        S.box(d, (1260, 600, 1840, 860), fill=S.WARN_BG, outline=S.WARN, a=a_w)
        S.text(d, (1290, 622), "EVIDENCE CHECK: OFF-CHAIN", 24, S.WARN, bold=True, a=a_w, bg=S.WARN_BG)
        for i, line in enumerate(["Verified by the VERIFIER_ROLE", "operator. The contract verifies",
                                  "no proof on chain; zk-ML proofs", "are roadmap."]):
            S.text(d, (1290, 666 + i * 44), line, 28, S.TEXT, a=a_w, bg=S.WARN_BG)

"""Scene 4, 01:10-01:30: protection and solvency, as the deployed contract actually has it.

The 20% buffer-pool split is NOT in BioRigCoreV5: bufferPool is only a stored address with an admin-only setter
and an event, and mintTree is non-payable. This scene labels the split as roadmap, on screen and in the captions.
"""
from __future__ import annotations

from tools import demo_style as S

TITLE = "Protection and solvency"
SECONDS = 20
ROADMAP_LABEL = "20% buffer-pool split: roadmap, not yet implemented"
CAPTIONS = [
    (0.3, 5.0, "Today the contract stores a buffer-pool address. Only the admin can change it, and each change "
               "emits BufferPoolUpdated."),
    (5.0, 10.0, "20% buffer-pool split: roadmap, not yet implemented. No mint moves any value today."),
    (10.0, 15.0, "Growth updates can only go up; a lower reading reverts. Reporting a death marks the tree dead "
                 "and frees its nullifier."),
    (15.0, 19.7, "BioRig on Celo Sepolia. Every contract is verified on Blockscout, so reviewers can read the "
                 "source."),
]
NARRATION = ("Today the contract stores a buffer pool address. Only the admin can change it, and each change "
             "emits an event. The twenty percent buffer pool split is roadmap, and not yet implemented. "
             "No mint moves any value today. Growth updates can only go up; a lower reading reverts. "
             "Reporting a death marks the tree dead and frees its nullifier. "
             "BioRig, on Celo Sepolia. Every contract is verified on Blockscout.")

# Illustrative growth series for the chart: monotonic, because updateTreeGrowth reverts InvalidGrowthData on any
# decrease. It is labelled on screen as illustrative: token #1 has no GrowthUpdated events yet.
SERIES = [312, 340, 371, 405, 446, 490]


def _chart(d, x0, y0, w, h, t, a, facts):
    S.box(d, (x0, y0, x0 + w, y0 + h), a=a)
    S.text(d, (x0 + 28, y0 + 22), "updateTreeGrowth · biomass (kg)", 28, S.TEXT, bold=True, a=a, bg=S.SURFACE)
    px0, py0, pw, ph = x0 + 70, y0 + 90, w - 120, h - 190
    d.line([(px0, py0 + ph), (px0 + pw, py0 + ph)], fill=S.fade(S.RULE, a), width=2)
    lo, hi = 280, 520
    pts = [(px0 + i * pw / (len(SERIES) - 1), py0 + ph - (v - lo) / (hi - lo) * ph) for i, v in enumerate(SERIES)]
    shown = S.clamp01((t - 10.3) / 3.0) * (len(pts) - 1)
    for i in range(len(pts) - 1):
        seg = S.clamp01(shown - i)
        if seg > 0:
            (xa, ya), (xb, yb) = pts[i], pts[i + 1]
            d.line([(xa, ya), (xa + (xb - xa) * seg, ya + (yb - ya) * seg)], fill=S.fade(S.OK, a), width=5)
    for i, (x, y) in enumerate(pts):
        if shown >= i:
            d.ellipse((x - 8, y - 8, x + 8, y + 8), fill=S.fade(S.OK, a))
            S.text(d, (x, y - 44), str(SERIES[i]), 22, S.TEXT, mono=True, anchor="ma", a=a, bg=S.SURFACE)
    S.text(d, (x0 + 28, y0 + h - 84), "lower reading → reverts InvalidGrowthData", 24, S.MUTED, a=a, bg=S.SURFACE)
    S.text(d, (x0 + 28, y0 + h - 48),
           f"illustrative series · token #{facts['token_id']} has {facts['growth_updates']} growth updates so far",
           22, S.MUTED, a=a, bg=S.SURFACE)


def draw(img, d, t, facts):
    body = S.window(t, 0.0, 15.2, 0.5)
    if body > 0:
        # buffer pool wiring as it exists
        a = body * S.ramp(t, 0.2)
        S.box(d, (80, 150, 880, 420), a=a)
        S.text(d, (110, 172), "bufferPool (stored address)", 28, S.MUTED, bold=True, a=a, bg=S.SURFACE)
        S.text(d, (110, 226), facts["buffer_pool"], 30, S.TEXT, mono=True, a=a, bg=S.SURFACE)
        S.text(d, (110, 290), "setBufferPool: DEFAULT_ADMIN_ROLE only", 28, S.TEXT, a=a, bg=S.SURFACE)
        S.text(d, (110, 336), "emits BufferPoolUpdated(old, new)", 28, S.TEXT, mono=True, a=a, bg=S.SURFACE)

        # the roadmap label: explicit and visible for the rest of the scene body
        r = body * S.ramp(t, 4.8, 0.6)
        S.box(d, (80, 450, 880, 880), fill=S.WARN_BG, outline=S.WARN, width=4, a=r)
        S.pill(d, (110, 474), "ROADMAP", fg=(20, 20, 20), bg=S.WARN, size=26, a=r)
        label = S.wrap(ROADMAP_LABEL, 40, 740, bold=True)
        for i, line in enumerate(label):
            S.text(d, (110, 540 + i * 52), line, 40, S.TEXT, bold=True, a=r, bg=S.WARN_BG)
        y_body = 540 + len(label) * 52 + 26
        for i, line in enumerate(["mintTree is non-payable and transfers", "nothing. No mint moves 20%, or any",
                                  "value, anywhere today."]):
            S.text(d, (110, y_body + i * 42), line, 30, S.TEXT, a=r, bg=S.WARN_BG)

        # growth + mortality
        g = body * S.ramp(t, 9.8, 0.6)
        _chart(d, 940, 150, 900, 520, t, g, facts)
        m = body * S.ramp(t, 12.2, 0.6)
        S.box(d, (940, 700, 1840, 880), a=m)
        S.text(d, (970, 722), "reportMortality(tokenId)", 30, S.TEXT, bold=True, mono=True, a=m, bg=S.SURFACE)
        S.text(d, (970, 776), "isAlive → false · nullifier released", 28, S.MUTED, a=m, bg=S.SURFACE)
        S.text(d, (970, 820), "dead trees cannot be updated (TreeIsDead)", 28, S.MUTED, a=m, bg=S.SURFACE)

    # closing card
    c = S.ramp(t, 15.0, 0.7)
    if c > 0:
        S.text(d, (S.W // 2, 250), "BioRig: Proof-of-Growth", 88, S.TEXT, bold=True, anchor="ma", a=c)
        S.text(d, (S.W // 2, 380), "proxy on Celo Sepolia", 34, S.MUTED, anchor="ma", a=c)
        S.text(d, (S.W // 2, 440), facts["proxy"], 40, S.CELO, mono=True, anchor="ma", a=c)
        host = facts["explorer"].replace("https://", "")
        S.text(d, (S.W // 2, 530), f"{host}/address/{facts['proxy'][:10]}…", 32, S.TEXT, mono=True, anchor="ma",
               a=c * S.ramp(t, 15.6))
        S.text(d, (S.W // 2, 620), "proxy · BioRigCoreV5 · ERC-6551 account · registry: all verified on Blockscout",
               28, S.MUTED, anchor="ma", a=c * S.ramp(t, 16.2))
        S.text(d, (S.W // 2, 700), ROADMAP_LABEL, 28, S.WARN, anchor="ma", a=c * S.ramp(t, 16.8))

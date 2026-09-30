"""Scene 1, 00:00-00:20: context. Title card, phone capture, the problem, the three-step answer."""
from __future__ import annotations

from tools import demo_style as S

TITLE = "Context"
SECONDS = 20
CAPTIONS = [
    (0.3, 6.0, "BioRig turns a smallholder's tree into a verifiable on-chain asset, on Celo."),
    (6.0, 13.0, "The problem: smallholders can grow trees, but cannot prove that growth to a financier."),
    (13.0, 19.7, "The approach: measure off-chain, register on-chain. One tree per NFT, each with its own wallet."),
]
NARRATION = ("BioRig turns a smallholder's tree into a verifiable on-chain asset, on Celo. "
             "The problem: smallholders can grow trees, but cannot prove that growth to a financier. "
             "The approach: measure off-chain, register on-chain. One tree per NFT, each with its own wallet.")


def _phone(d, x, y, a, t):
    S.box(d, (x, y, x + 300, y + 560), fill=S.SURFACE, outline=S.MUTED, width=4, radius=40, a=a)
    S.box(d, (x + 20, y + 50, x + 280, y + 490), fill=S.FIELD, outline=S.FIELD, radius=12, a=a)
    # tree
    trunk = S.fade((120, 84, 52), a)
    d.rectangle((x + 136, y + 270, x + 164, y + 470), fill=trunk)
    for cx, cy, r in ((150, 210, 90), (100, 260, 60), (200, 260, 60)):
        d.ellipse((x + cx - r, y + cy - r, x + cx + r, y + cy + r), fill=S.fade(S.GREEN, a))
    # measurement sweep across the trunk
    m = S.ramp(t, 8.0, 1.2)
    if m > 0:
        yy = y + 380
        d.line([(x + 110, yy), (x + 110 + 80 * m, yy)], fill=S.fade(S.CELO, a), width=4)
        S.text(d, (x + 150, yy - 44), "DBH", 24, S.CELO, bold=True, anchor="ma", a=a * m, bg=S.FIELD)
    S.text(d, (x + 150, y + 505), "capture", 22, S.MUTED, anchor="ma", a=a)


def draw(img, d, t, facts):
    # title card
    a_title = S.window(t, 0.0, 6.4, 0.6)
    if a_title > 0:
        S.text(d, (S.W // 2, 330), "BioRig: Proof-of-Growth", 104, S.TEXT, bold=True, anchor="ma", a=a_title)
        S.text(d, (S.W // 2, 470), "smallholder capture  →  verifiable asset", 44, S.MUTED, anchor="ma", a=a_title)
        S.pill(d, (S.W // 2 - 250, 580), f"built on Celo  ·  Celo Sepolia  ·  chain {facts['chain_id']}",
               fg=(20, 20, 20), bg=S.CELO, size=28, a=a_title)

    # the problem
    a_prob = S.window(t, 6.0, 13.4, 0.6)
    if a_prob > 0:
        _phone(d, 260, 200, a_prob, t)
        S.text(d, (700, 260), "The problem", 34, S.MUTED, bold=True, a=a_prob)
        for i, line in enumerate(["A smallholder can plant and grow", "trees, but cannot prove that growth",
                                  "to a financier."]):
            S.text(d, (700, 330 + i * 72), line, 56, S.TEXT, bold=True, a=a_prob)
        S.text(d, (700, 580), "No trusted record of what was planted, where, or how it grows.", 32, S.MUTED,
               a=S.ramp(t, 8.5) * a_prob)

    # the approach
    a_ans = S.window(t, 13.0, 20.5, 0.6)
    if a_ans > 0:
        steps = [("1", "Capture", "phone photo + GPS"), ("2", "Verify", "off-chain measurement"),
                 ("3", "Mint", "ERC-721 + ERC-6551 wallet")]
        for i, (n, head, sub) in enumerate(steps):
            a = a_ans * S.ramp(t, 13.3 + i * 0.7)
            x = 190 + i * 540
            S.box(d, (x, 330, x + 440, 620), a=a)
            S.text(d, (x + 40, 360), n, 40, S.ACCENT, bold=True, mono=True, a=a)
            S.text(d, (x + 40, 440), head, 60, S.TEXT, bold=True, a=a)
            S.text(d, (x + 40, 530), sub, 30, S.MUTED, a=a)
            if i < 2:
                S.arrow(d, (x + 455, 475), (x + 525, 475), S.ramp(t, 13.8 + i * 0.7))
        S.text(d, (S.W // 2, 700), "one tree  =  one NFT  =  one on-chain wallet", 38, S.TEXT, anchor="ma",
               a=a_ans * S.ramp(t, 15.5))

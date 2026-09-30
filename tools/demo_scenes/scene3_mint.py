"""Scene 3, 00:45-01:10: on-chain minting. The mintTree call path and the real token #1 transaction."""
from __future__ import annotations

from tools import demo_style as S

TITLE = "On-chain minting"
SECONDS = 25
CAPTIONS = [
    (0.3, 6.0, "Only an account holding VERIFIER_ROLE can call mintTree. It calls the ERC1967 proxy on Celo "
               "Sepolia."),
    (6.0, 12.0, "The contract records the tree and has the ERC-6551 registry create the tree's own token-bound "
                "account."),
    (12.0, 18.0, "That account must have code, report ERC-6551 support, and be bound to this chain, this contract "
                 "and this token id, or the mint reverts."),
    (18.0, 24.7, "A real transaction: token #1, minted on Celo Sepolia at deployment. Its wallet is live on chain."),
]
NARRATION = ("Only an account holding the verifier role can call mint tree. It calls the proxy on Celo Sepolia. "
             "The contract records the tree, and has the ERC six five five one registry create the tree's own "
             "token bound account. That account must be bound to this chain, this contract and this token, or "
             "the mint reverts. Here is a real transaction: token number one, minted on Celo Sepolia. "
             "Its wallet is live on chain.")

NODES = [  # (key, x, y, title, subtitle, appear_at)
    ("verifier", 90, 190, "verifier", "VERIFIER_ROLE", 0.3),
    ("proxy", 560, 190, "mintTree", "ERC1967 proxy", 1.4),
    ("nft", 1030, 190, "ERC-721", "TREE #{token_id}", 3.2),
    ("registry", 560, 440, "registry", "createAccount", 6.2),
    ("tba", 1030, 440, "ERC-6551 TBA", "token-bound account", 7.6),
]
NW, NH = 380, 170


def _node(d, x, y, title, sub, a, active):
    S.box(d, (x, y, x + NW, y + NH), outline=S.ACCENT if active else S.RULE, width=3 if active else 2, a=a)
    S.text(d, (x + 28, y + 30), title, 42, S.TEXT, bold=True, a=a, bg=S.SURFACE)
    S.text(d, (x + 28, y + 100), sub, 28, S.MUTED, mono=True, a=a, bg=S.SURFACE)


def draw(img, d, t, facts):
    pos = {k: (x, y) for k, x, y, *_ in NODES}
    for key, x, y, title, sub, at in NODES:
        _node(d, x, y, title, sub.format(token_id=facts["token_id"]), S.ramp(t, at), active=at <= t < at + 2.5)

    def edge(a, b, start, side="h"):
        (ax, ay), (bx, by) = pos[a], pos[b]
        if side == "h":
            S.arrow(d, (ax + NW + 8, ay + NH / 2), (bx - 12, by + NH / 2), S.ramp(t, start, 0.8))
        else:
            S.arrow(d, (ax + NW / 2, ay + NH + 8), (bx + NW / 2, by - 12), S.ramp(t, start, 0.8))

    edge("verifier", "proxy", 0.9)
    edge("proxy", "nft", 2.6)
    edge("proxy", "registry", 5.6, "v")
    edge("registry", "tba", 7.0)

    # validation checks beside the TBA
    a_c = S.ramp(t, 11.8, 0.6)
    checks = ["has code", "ERC-165 0x6faff5f1", f"token() = ({facts['tba_bound_token'][0]},",
              "   proxy, #%d)" % facts["token_id"]]
    for i, c in enumerate(checks):
        a = a_c * S.ramp(t, 12.2 + i * 0.6)
        S.text(d, (1450, 450 + i * 42), ("✓ " if not c.startswith("   ") else "  ") + c, 28,
               S.OK if not c.startswith("   ") else S.OK, mono=True, a=a)

    # the real transaction
    a_tx = S.ramp(t, 17.8, 0.8)
    if a_tx > 0:
        S.box(d, (90, 660, 1830, 890), a=a_tx)
        S.pill(d, (120, 680), "CONFIRMED ON CELO SEPOLIA", size=22, a=a_tx)
        rows = [("tx", facts["mint_tx"]),
                ("block · gas", f"{facts['mint_block']:,}  ·  {facts['mint_gas_used']:,} gas"),
                ("token-bound account", facts["tba"])]
        for i, (k, v) in enumerate(rows):
            a = a_tx * S.ramp(t, 18.3 + i * 0.6)
            S.text(d, (120, 744 + i * 46), k, 28, S.MUTED, a=a, bg=S.SURFACE)
            S.text(d, (520, 744 + i * 46), v, 28, S.TEXT, mono=True, a=a, bg=S.SURFACE)
        S.text(d, (1800, 690), f"token #{facts['token_id']} · deployment smoke mint", 22, S.MUTED, anchor="ra",
               a=a_tx, bg=S.SURFACE)

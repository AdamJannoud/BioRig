# BioRig brand kit

Design and artwork: **Adam Jannoud** ([@AdamJannoud](https://github.com/AdamJannoud)). Every file here carries
that credit (SVG `<desc>`, PNG `Author`/`Copyright` text chunks). All rights reserved.

The mark is direction B, **the canopy of two rings**: Celo's interlocking rings become the tree's canopy, the
forest trunk and the node carry the regenerative and the biometric halves of the project.

| file | use |
| --- | --- |
| `biorig-mark.svg` / `.png` | brandmark on light backgrounds |
| `biorig-mark-reverse.svg` / `.png` | brandmark in gold, on forest or dark backgrounds |
| `biorig-lockup.svg` / `.png` | horizontal lockup (mark + wordmark on a forest tile): proposal cover, README, social card |
| `biorig-icon-64.svg`, `biorig-icon-32.svg` | the step-down: two rings at 64 px, one ring at 32 px |
| `favicon.svg`, `favicon-16.png`, `favicon-32.png`, `favicon.ico` | below 32 px: one ring on a forest tile, drawn on the 16 px grid |
| `alternates/` | directions A (growth rings) and C (hex, the plot cell), kept as alternates |

## Palette

| token | hex | role |
| --- | --- | --- |
| gold | `#FCFF52` | Celo gold: primary actions, the mark on forest |
| gold deep | `#E8EC2A` | the mark's rings on light backgrounds, the wordmark's dot |
| gold ink | `#1A1C00` | text on gold |
| forest | `#023A24` | trunk, wordmark, tiles |
| forest 2 | `#0A5B3A` | links and accents on light backgrounds |
| cream | `#F7F5EE` | page background, light |
| dark | `#06170F` | page background, dark |

## Regenerating

Everything except `alternates/` and this file is written by `tools/generate_brand.py` from one set of primitives
(the SVG writer and a Pillow painter share it, so each PNG is painted from the same geometry as its SVG). The
dashboard's copies live in `dashboard/brand/`, written by the same run.

    .venv/bin/python tools/generate_brand.py          # write
    .venv/bin/python tools/generate_brand.py --check  # exit 1 if anything is stale

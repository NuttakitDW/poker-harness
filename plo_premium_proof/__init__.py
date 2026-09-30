"""Independent CFR test of whether Hwang-Premium hands ever fold first-in.

The game is the same six-max PLO4 chip-EV table as :mod:`plo_chipev_fast`
(100bb, pot-only raises, two-raise cap, forced postflop check-down), but the
hand abstraction never mixes Hwang tiers, and every Premium class is re-checked
with an exact best response against the solved profile.
"""

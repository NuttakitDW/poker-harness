"""Dense, static-tree backend for the fixed six-seat PLO chip-EV experiment.

This is an accelerated research approximation with a feature abstraction and a
forced post-flop check-down.  It is not an ordinary-PLO or GTO claim.
"""

from .hands import HandLookup
from .model import DenseModel
from .trainer import FastTrainer
from .tree import PublicTree

__all__ = ["DenseModel", "FastTrainer", "HandLookup", "PublicTree"]


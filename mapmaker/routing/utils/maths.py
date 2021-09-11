#===============================================================================

from math import sqrt

#===============================================================================

def add(u: list, v: list) -> list:
    return [x + v[n] for n, x in enumerate(u)]

def magnitude(v: list) -> float:
    return sqrt(sum(x * x for x in v))

def mult(u: list, c: float) -> list:
    return [x * c for x in u]

def normalize(v: list) -> list:
    vmag = magnitude(v)
    return [x / vmag for x in v]

def set_magnitude(v: list, mag: float) -> list:
    scale = mag / magnitude(v)
    return [x * scale for x in v]

def sub(u: list, v: list) -> list:
    return [x - v[n] for n, x in enumerate(u)]

#===============================================================================

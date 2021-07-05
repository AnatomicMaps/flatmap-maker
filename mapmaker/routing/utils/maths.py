from math import sqrt


def add(u, v):
    return [u[i] + v[i] for i in range(len(u))]


def magnitude(v):
    return sqrt(sum(v[i] * v[i] for i in range(len(v))))


def mult(u, c):
    return [u[i] * c for i in range(len(u))]


def normalize(v):
    vmag = magnitude(v)
    return [v[i] / vmag for i in range(len(v))]


def set_magnitude(v, mag):
    scale = mag / sqrt(sum(c * c for c in v))
    return [c * scale for c in v]


def sub(u, v):
    return [u[i] - v[i] for i in range(len(u))]

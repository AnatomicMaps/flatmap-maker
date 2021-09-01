from math import sqrt


def add(u: list, v: list) -> list:
    return [u[i] + v[i] for i in range(len(u))]


def magnitude(v: list):
    return sqrt(sum(v[i] * v[i] for i in range(len(v))))


def mult(u: list, c):
    return [u[i] * c for i in range(len(u))]


def normalize(v: list):
    vmag = magnitude(v)
    return [v[i] / vmag for i in range(len(v))]


def set_magnitude(v: list, mag):
    scale = mag / sqrt(sum(c * c for c in v))
    return [c * scale for c in v]


def sub(u: list, v: list):
    return [u[i] - v[i] for i in range(len(u))]

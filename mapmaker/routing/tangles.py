def tangles(permutation, debug=False):
    max_m = len(permutation) - 1
    p = permutation.copy()
    for n, m in enumerate(permutation):
        if n > m:   #  assert p[m] == n, i.e. p[p[n]] == n
            p[n] = n
    if debug: print(permutation, '-->', p)
    tangles = 0
    i = 0 if p[0] < max_m else 1
    while i < max_m:
        m = p[i]
        j = i + 1
        while j < p[i]:
            if p[j] > m:
                tangles += 1
            if debug: print('  ', i, m, '  ', j, p[j], '  ', tangles)
            j += 1
        i += 1
    if debug: print('    -->', tangles)
    return tangles


def test(p):
    return tangles([a-1 for a in p])

permutations = [
    [6, 3, 2, 5, 4, 1],
    [6, 4, 5, 2, 3, 1],
    [5, 3, 2, 6, 1, 4],
    [5, 4, 6, 2, 1, 3],
    [4, 6, 5, 1, 3, 2],
    [4, 5, 6, 1, 2, 3],
    [3, 6, 1, 5, 4, 2],
    [3, 5, 1, 6, 2, 4],
    [4, 3, 2, 1],
    [3, 4, 1, 2],
]

for p in permutations:
    print(p, '-->', test(p))

#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020-21  David Brooks
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
#===============================================================================

import itertools

#===============================================================================

from permutation import Permutation

#===============================================================================

def tangles(permutation):
    p = [a-1 for a in permutation.to_image()]
    for n, m in enumerate(p):
        if n > m:   #  assert p[m] == n, i.e. p[p[n]] == n
            p[n] = n
    tangles = 0
    max_m = len(p) - 1
    i = 0 if p[0] < max_m else 1
    while i < max_m:
        m = p[i]
        j = i + 1
        while j < p[i]:
            if p[j] > m:
                tangles += 1
            j += 1
        i += 1
    return tangles

#===============================================================================

def permutations(N):
    for p in itertools.permutations(range(N)):
        if len([n for n, a in enumerate(p) if n == a]) == 0:
            perm = Permutation(*[a+1 for a in p])
            if len(perm.to_cycles()) == N/2:
                yield perm

#===============================================================================

def branch(cable_connections):
    port_pins = [a + cable_connections[n+1] for n, a in enumerate(cable_connections[:-1])]
    port_pins.append(cable_connections[-1] + cable_connections[0])
    for perm in permutations(sum(port_pins)):
        inside_port = False
        start_pin1 = 1
        for pin_count in port_pins:
            next_pin1 = start_pin1 + pin_count
            for pin in range(start_pin1, next_pin1):
                if start_pin1 <= perm(pin) < next_pin1:
                    inside_port = True
                    break
            if inside_port:
                break
            start_pin1 = next_pin1
        if not inside_port:
            yield perm

#===============================================================================

test_permutations = [
    [1, 2, 3, 4, 5, 6, 7],
    [6, 3, 2, 5, 4, 1, 7],
    [6, 4, 5, 2, 3, 1],
    [6, 4, 3, 2, 7, 1, 5],
    [5, 3, 2, 6, 1, 4],
    [5, 4, 6, 2, 1, 3],
    [4, 6, 5, 1, 3, 2],
    [4, 5, 6, 1, 2, 3],
    [3, 6, 1, 5, 4, 2],
    [3, 5, 1, 6, 2, 4],
    [4, 3, 2, 1],
    [3, 4, 1, 2],
]

#===============================================================================

def test(N):
    for perm in permutations(N):
        t = tangles(perm)
        print(t, perm.to_image())

if __name__ == '__main__':
    for p in branch((2, 1, 0)):
    #for p in branch((1, 1, 1)):
        print(tangles(p), p.to_image())
    #for n in range(1, N+1):
    #    test(n)
    #    print()

#===============================================================================

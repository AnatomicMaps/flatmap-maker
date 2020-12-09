#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020  David Brooks
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

from math import sin, cos, tan

#===============================================================================

import numpy as np

#===============================================================================

from mapmaker.geometry import Transform

#===============================================================================

class SVGTransform(Transform):
    def __init__(self, transform):
        T = np.identity(3)
        if transform is not None:
            # A simple parser, assuming well-formed SVG
            tokens = transform.replace('(', ' ').replace(')', ' ').replace(',', ' ').split()
            pos = 0
            while pos < len(tokens):
                xfm = tokens[pos]
                pos += 1
                if xfm == 'matrix':
                    params = tuple(float(x) for x in tokens[pos:pos+6])
                    pos += 6
                    T = T@np.array([[params[0], params[2], params[4]],
                                    [params[1], params[3], params[5]],
                                    [        0,         0,         1]])
                elif xfm == 'translate':
                    x = float(tokens[pos])
                    pos += 1
                    if tokens[pos].isalpha():
                        y = 0
                    else:
                        y = float(tokens[pos])
                        pos += 1
                    T = T@np.array([[1, 0, x],
                                    [0, 1, y],
                                    [0, 0, 1]])
                elif xfm == 'scale':
                    sx = float(tokens[pos])
                    pos += 1
                    if tokens[pos].isalpha():
                        sy = sx
                    else:
                        sy = float(tokens[pos])
                        pos += 1
                    T = T@np.array([[sx,  0, 0],
                                    [ 0, sy, 0],
                                    [ 0,  0, 1]])
                elif xfm == 'rotate':
                    a = float(tokens[pos])
                    pos += 1
                    if tokens[pos].isalpha():
                        T = T@np.array([[cos(a), -sin(a), 0],
                                        [sin(a),  cos(a), 0],
                                        [     0,       0, 1]])
                    else:
                        (cx, cy) = tuple(float(x) for x in tokens[pos:pos+2])
                        pos += 2
                        T = T@np.array([[cos(a), -sin(a), 0],
                                        [sin(a),  cos(a), 0],
                                        [     0,       0, 1]])

                elif xfm == 'skewX':
                    a = float(tokens[pos])
                    pos += 1
                    T = T@np.array([[1, tan(a), 0],
                                    [0,      1, 0],
                                    [0,      0, 1]])
                elif xfm == 'skewY':
                    a = float(tokens[pos])
                    pos += 1
                    T = T@np.array([[     1, 0, 0],
                                    [tan(a), 1, 0],
                                    [     0, 0, 1]])
                else:
                    raise ValueError('Invalid SVG transform: {}'.format(transform))
        super().__init__(T)

#===============================================================================

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

from shapely.geometry import LineString, Polygon
import shapely.ops

#===============================================================================

END_MATCH_RATIO      = 0.9
ALMOST_TOUCHING_EMUS = 100

#===============================================================================

class LineMatcher(object):
    def __init__(self, first_line):
        self._previous = LineString(first_line)
        self._coords = []

    @property
    def coords(self):
        return self._coords

    @property
    def line(self):
        return LineString(self._coords)

    @property
    def previous(self):
        return self._previous

    def extend(self, line):
        pt = self._previous.intersection(line)
        if not pt.is_empty:
            where = self._previous.project(pt, True)
            if where >= END_MATCH_RATIO:   # Near previous's end
                self._coords.extend(shapely.ops.substring(self._previous, 0, where, True).coords)
                where = line.project(pt, True)
                if where <= (1.0 - END_MATCH_RATIO):
                    self._previous = shapely.ops.substring(line, where, 1, True)
                elif where >= END_MATCH_RATIO:
                    self._previous = LineString(reversed(shapely.ops.substring(line, 0, where, True).coords))
            else:
                return False
        else:
            # Find which line end is closest to previous's end
            end = self._previous.boundary[1]
            if end.distance(line.boundary[0]) <= ALMOST_TOUCHING_EMUS:
                self._coords.extend(self._previous.coords)
                self._previous = line
            elif end.distance(line.boundary[1]) <= ALMOST_TOUCHING_EMUS:
                self._coords.extend(self._previous.coords)
                self._previous = LineString(reversed(line.coords))
            else:
                return False
        return True

#===============================================================================

def make_boundary(line_segments):
    lines = list(line_segments)
    line_matcher = LineMatcher(lines[0])
    remainder = lines[1:]
    while len(remainder) > 0:
        for (n, line) in enumerate(remainder):
            if line_matcher.extend(line):
                del remainder[n]
                break
            else:
                if n == (len(remainder) - 1):
                    raise ValueError("Boundary segment doesn't have a close neighbour")
    if line_matcher.extend(lines[0]):
        coords = line_matcher.coords
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        return Polygon(coords)
    else:
        raise ValueError("Boundary segment doesn't have a close neighbour")

#===============================================================================

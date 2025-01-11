#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2018 - 2025  David Brooks
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

from dataclasses import dataclass, field
import itertools
import math
from typing import Any, Optional

#===============================================================================

import networkx as nx
from shapely.geometry import LineString, Polygon

#===============================================================================

from mapmaker.utils import log

from . import Shape
from .constants import EPSILON, MAX_PARALLEL_SKEW, MAX_LINE_WIDTH, MIN_LINE_ASPECT_RATIO

#===============================================================================

type Coordinate = tuple[float, float]

#===============================================================================

@dataclass
class XYPair:
    x: float
    y: float
    properties: dict[str, Any] = field(default_factory=dict)

    @property
    def magnitude(self) -> float:
        return math.sqrt(self.x*self.x + self.y*self.y)

    @property
    def coords(self) -> tuple[float, float]:
        return (self.x, self.y)

    def distance(self, other: 'XYPair') -> float:
        dx = other.x - self.x
        dy = other.y - self.y
        return math.sqrt(dx*dx + dy*dy)

    def midpoint(self, other: 'XYPair') -> 'XYPair':
        return XYPair((self.x + other.x)/2, (self.y + other.y)/2)

#===============================================================================

class Rotation:
    def __init__(self, delta: XYPair):
        assert delta.x != 0 or delta.y != 0
        hypotenuse = delta.magnitude
        self.__cos_theta = delta.x/hypotenuse
        self.__sin_theta = delta.y/hypotenuse

    @property
    def cos_theta(self):
        return self.__cos_theta

    @property
    def matrix(self):
        return [[ self.__cos_theta, self.__sin_theta],
                [-self.__sin_theta, self.__cos_theta]]

    @property
    def sin_theta(self):
        return self.__sin_theta

    def rotate(self, point: XYPair, direction=1) -> XYPair:
    #======================================================
        if direction >= 0:
            return XYPair( point.x*self.__cos_theta + point.y*self.__sin_theta,
                          -point.x*self.__sin_theta + point.y*self.__cos_theta)
        else:
            return XYPair(point.x*self.__cos_theta - point.y*self.__sin_theta,
                          point.x*self.__sin_theta + point.y*self.__cos_theta)

#===============================================================================

@dataclass
class Line:
    p0: XYPair
    p1: XYPair

    def __post_init__(self):
        delta_x = self.p1.x - self.p0.x
        delta_y = self.p1.y - self.p0.y
        self.__delta = XYPair(delta_x, delta_y)
        self.__rotation = None  # Lazy evaluate

    def __hash__(self):
        return hash(((self.p0.x, self.p0.y), (self.p1.x, self.p1.y)))

    @property
    def coords(self):
        return (self.p0.coords, self.p1.coords)

    @property
    def delta(self) -> XYPair:
        return self.__delta

    @property
    def rotation(self) -> Rotation:
        if self.__rotation is None:
            self.__rotation = Rotation(self.__delta)
        return self.__rotation

    def intersection(self, other: 'Line') -> Optional[XYPair]:
        d = self.__delta.x*other.__delta.y - self.__delta.y*other.__delta.x
        if d != 0:
            c0 = self.p0.x - other.p0.x
            c1 = self.p0.y - other.p0.y
            s = (c1*other.__delta.x - c0*other.__delta.y)/d
            t = (c1*self.__delta.x  - c0*self.__delta.y)/d
            if (0 <= s <= 1) and (0 <= t <= 1):
                return XYPair(self.p0.x + s*self.__delta.x,
                              self.p0.y + s*self.__delta.y)
        return None

    def parallel(self, other: 'Line') -> bool:
        return abs(self.rotation.cos_theta*other.rotation.sin_theta
                 - self.rotation.sin_theta*other.rotation.cos_theta) < MAX_PARALLEL_SKEW

#===============================================================================

class HorizontalLine:
    def __init__(self, x0, x1, y):
        assert x0 != x1, f'Horizontal line ends are not distinct: {x0} and {x1}'
        if x0 < x1:
            self.__x_min = x0
            self.__x_max = x1
        else:
            self.__x_min = x1
            self.__x_max = x0
        self.__y = y
        self.__rotation = Rotation(XYPair(1, 0))

    def __str__(self):
        return f'[{self.__x_min}, {self.__x_max}] at {self.__y}'

    @classmethod
    def from_line(cls, line: Line) -> 'HorizontalLine':
    #==================================================
        self = super().__new__(cls)
        p0 = line.rotation.rotate(line.p0)
        p1 = line.rotation.rotate(line.p1)
        assert abs(p0.y - p1.y) < EPSILON, f'Rotated points should be horizontal: {p0} and {p1}'
        self.__init__(p0.x, p1.x, p0.y)
        self.__rotation = line.rotation
        return self

    @property
    def length(self):
        return self.__x_max - self.__x_min

    @property
    def x_min(self):
        return self.__x_min

    @property
    def x_max(self):
        return self.__x_max

    @property
    def y(self):
        return self.__y

    def project(self, line: Line) -> 'HorizontalLine':
    #=================================================
        p0 = self.__rotation.rotate(line.p0)
        p1 = self.__rotation.rotate(line.p1)
        return HorizontalLine(p0.x, p1.x, p0.y)

    def mid_line(self, other: 'HorizontalLine') -> Line:
    #===================================================
        w = (self.__y + other.__y)/2
        p0 = XYPair(min(self.__x_min, other.__x_min), w)
        p1 = XYPair(max(self.__x_max, other.__x_max), w)
        return Line(self.__rotation.rotate(p0, -1), self.__rotation.rotate(p1, -1))

    def overlap(self, other: 'HorizontalLine') -> float:
    #===================================================
        if self.__x_max <= other.__x_min or self.__x_min >= other.__x_max:
            return 0
        elif self.__x_max <= other.__x_max and self.__x_min >= other.__x_min:
            return self.length
        elif self.__x_max > other.__x_max and self.__x_min < other.__x_min:
            return other.length
        elif self.__x_max >= other.__x_min:
            return self.__x_max - other.__x_min
        else: # self._x_min <= other.__x_max
            return other.__x_max - self.__x_min

    def separation(self, other: 'HorizontalLine') -> float:
    #======================================================
        return abs(self.__y - other.__y)

#===============================================================================
## Arrow detection
## non-parallel intersecting lines
##
## 4 lines make up an arrowhead
##
##                      |\
##                ------  \
##                ------  /
##                      |/
##
## Should have max one arrow per line
##
#===============================================================================

class LineFinder:
    def __init__(self, scaling: float):
        self.__epsilon = scaling*EPSILON
        self.__max_line_width = scaling*MAX_LINE_WIDTH

    def get_line(self, shape: Shape) -> Optional[LineString]:
    #========================================================
        ends_graph = nx.Graph()
        used_lines: set[Line] = set()
        mid_lines: list[Line] = []
        boundary_coords = shape.geometry.boundary.simplify(self.__epsilon).coords
        boundary_line_coords = zip(boundary_coords, boundary_coords[1:])
        n = 0
        for (line0, line1) in itertools.combinations(boundary_line_coords, 2):
            l0 = Line(XYPair(*line0[0]), XYPair(*line0[1]))
            l1 = Line(XYPair(*line1[0]), XYPair(*line1[1]))
            if l0.parallel(l1):
                p0 = HorizontalLine.from_line(l0)
                p1 = p0.project(l1)

                if trace:
                    print('PAR', p0.separation(p1), self.__max_line_width, p0.overlap(p1), shape.id, p0, p1)

                if ((w := p0.separation(p1)) <= self.__max_line_width
                 and p0.overlap(p1) > MIN_LINE_ASPECT_RATIO*w):
                    mid_lines.append(p0.mid_line(p1))
                    used_lines.update([l0, l1])
            elif (pt := l0.intersection(l1)) is not None:
                ends_graph.add_edge(l0, l1, intersection=pt)
            n += 1
        ends_graph.remove_nodes_from(used_lines)
        if len(mid_lines) == 1:
            # Only a single line segment
            line_points = [mid_lines[0].p0, mid_lines[0].p1]
        elif len(mid_lines) == 0:
            line_points = []
        else:
            G = nx.Graph()
            for (l0, l1) in itertools.combinations(mid_lines, 2):
                pt = l0.intersection(l1)
                if pt is not None:
                    G.add_edge(l0, l1, intersection=pt)
            end_lines = []
            try:
                for (l, d) in G.degree:
                    if d == 0:
                        raise ValueError(f'Isolated line: {l}')
                    elif d == 1:
                        end_lines.append(l)
                    elif d > 2:
                        raise ValueError(f'Line is too connected: {l} {G[l]}')
                assert len(end_lines) == 2, f"Shape as line doesn't have two ends: {end_lines}"
            except (ValueError, AssertionError) as err:
                log.warning(str(err), shape=shape.id)
                return None

            start_line = end_lines[0]
            last_line = end_lines[1]
            segments = nx.shortest_path(G, start_line, last_line)
            line_points = [G.edges[l0, l1]['intersection']
                            for (l0, l1) in itertools.pairwise(segments)]
            if start_line.p0.distance(line_points[0]) > start_line.p1.distance(line_points[0]):
                line_points.insert(0, start_line.p0)
            else:
                line_points.insert(0, start_line.p1)
            if last_line.p0.distance(line_points[-1]) > last_line.p1.distance(line_points[-1]):
                line_points.append(last_line.p0)
            else:
                line_points.append(last_line.p1)

        if len(ends_graph):
            for end_nodes in nx.connected_components(ends_graph):
                if len(end_nodes) == 4:     # We most likely have an arrow head
                    arrow_graph = ends_graph.subgraph(end_nodes)
                    points = [e[2] for e in arrow_graph.edges(data='intersection')]
                    # The following assumes that the arrow head is an isosceles triangle that isn't equilateral
                    distances = [ p0.distance(p1)
                                    for (p0, p1) in itertools.pairwise(points + [points[0]])]
                    for (n, (d0, d1)) in enumerate(itertools.pairwise([distances[-1]] + distances)):
                        if abs(d0 - d1) <= EPSILON:
                            arrow_line = Line(points[n-2].midpoint(points[n-1]), points[n])
                            if arrow_line.p0.distance(line_points[0]) < arrow_line.p0.distance(line_points[-1]):
                                line_points[0] = arrow_line.p1
                                line_points.reverse()
                            else:
                                line_points[-1] = arrow_line.p1
                            shape.properties['directional'] = True
                            break

        return LineString([pt.coords for pt in line_points]) if len(line_points) >= 2 else None

#===============================================================================

if __name__ == '__main__':
    shape = Shape(None, Polygon([[0, 0], [2, 0], [2, 3], [5, 3], [5, 2.95], [6, 3.1],
                     [5, 3.25], [5, 3.2], [1.8, 3.2], [1.8, 0.2], [0, 0.2], [0, 0]]))
    line_finder = LineFinder(1)
    points = line_finder.get_line(shape)
    print(points)

#===============================================================================

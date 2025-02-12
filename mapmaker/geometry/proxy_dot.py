#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020 - 2024 David Brooks
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

import shapely
from shapely import LineString, MultiPolygon, Polygon

#===============================================================================

def proxy_dot(poly: MultiPolygon|Polygon, proxy_seq: int) -> Polygon:
    envelope_coords = shapely.oriented_envelope(poly).boundary.coords
    edge_coords = list(zip(envelope_coords, envelope_coords[1:]))
    edges = [LineString(coords) for coords in edge_coords]
    minor_axis = 1 if edges[0].length >= edges[1].length else 0

    p0 = shapely.line_interpolate_point(edges[minor_axis], 0.5, normalized=True)
    p1 = shapely.line_interpolate_point(edges[minor_axis+2], 0.5, normalized=True)
    if p0.coords[0][1] < p1.coords[0][1]:
        median_line = LineString([p0, p1])
    else:
        median_line = LineString([p1, p0])
    distance = 0.8 - proxy_seq * 0.15
    proxy_point = shapely.line_interpolate_point(median_line, distance, normalized=True)
    median_distance = median_line.length/16 if median_line.length/16 < 1000 else 1000
    return proxy_point.buffer(median_distance)

#===============================================================================

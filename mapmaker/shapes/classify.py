#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2018 - 2024  David Brooks
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

from collections import defaultdict
from typing import DefaultDict, Iterable, Optional

#===============================================================================

from shapely.geometry.base import BaseGeometry
import shapely.prepared
import shapely.strtree

#===============================================================================

from mapmaker.settings import settings
from mapmaker.shapes import Shape, SHAPE_TYPE
from mapmaker.utils import log

from .line_finder import LineFinder
from .text_finder import TextFinder

#===============================================================================

"""

Mutually exclusive shape categories:

    parent: Shape
    children: list[Shape]
    overlapping: list[Shape]
    adjacent: list[Shape]

Shape types from size (area and aspect ratio) and geometry:

*   Component
*   Container
*   Boundary
*   Connection
*   Text

"""

#===============================================================================

class ShapeClassifier:
    def __init__(self, shapes: list[Shape], map_area: float, metres_per_pixel: float):
        self.__shapes = list(shapes)
        self.__shapes_by_type: DefaultDict[SHAPE_TYPE, list[Shape]] = defaultdict(list[Shape])
        self.__geometry_to_shape: dict[int, Shape] = {}
        self.__line_finder = LineFinder(metres_per_pixel)
        self.__text_finder = TextFinder(metres_per_pixel)
        geometries = []
        for n, shape in enumerate(shapes):
            geometry = shape.geometry
            area = geometry.area
            self.__bounds = geometry.bounds
            width = abs(self.__bounds[2] - self.__bounds[0])
            height = abs(self.__bounds[3] - self.__bounds[1])
            bbox_coverage = (width*height)/map_area
            if width > 0 and height > 0:
                aspect = min(width, height)/max(width, height)
                coverage = area/(width*height)
            else:
                aspect = 0
                coverage = 1
            shape.properties.update({
                'area': area,
                'aspect': aspect,
                'coverage': coverage,
                'bbox-coverage': bbox_coverage,
            })
            if shape.shape_type == SHAPE_TYPE.UNKNOWN:
                if bbox_coverage > 0.001 and geometry.geom_type == 'MultiPolygon':
                    shape.properties['shape-type'] = SHAPE_TYPE.BOUNDARY
                elif ((n < len(shapes) - 1) and shapes[n+1].shape_type == SHAPE_TYPE.TEXT
                  and coverage < 0.5 and bbox_coverage < 0.001):
                    shape.properties['exclude'] = True
                elif coverage < 0.4 or 'LineString' in geometry.geom_type:
                    if not self.__check_connection(shape):
                        log.warning('Cannot extract line from polygon', shape=shape.id)
                elif bbox_coverage > 0.001 and coverage > 0.9:
                    shape.properties['shape-type'] = SHAPE_TYPE.CONTAINER
                elif bbox_coverage < 0.0005 and aspect > 0.9 and 0.7 < coverage <= 0.85:
                    shape.properties['shape-type'] = SHAPE_TYPE.COMPONENT
                elif bbox_coverage < 0.001 and coverage > 0.85:
                    shape.properties['shape-type'] = SHAPE_TYPE.COMPONENT
                elif not self.__check_connection(shape):
                    log.warning('Unclassifiable shape', shape=shape.id, geometry=shape.properties.get('geometry'))
                    shape.properties['colour'] = 'yellow'
            if not shape.properties.get('exclude', False):
                self.__shapes_by_type[shape.shape_type].append(shape)
                if shape.shape_type != SHAPE_TYPE.CONNECTION:
                    self.__geometry_to_shape[id(shape.geometry)] = shape
                    geometries.append(shape.geometry)

        self.__str_index = shapely.strtree.STRtree(geometries)
        geometries: list[BaseGeometry] = self.__str_index.geometries     # type: ignore
        parent_child = []
        for geometry in geometries:
            if geometry.area > 0:
                parent = self.__geometry_to_shape[id(geometry)]
                for child in [self.__geometry_to_shape[id(geometries[c])]
                                for c in self.__str_index.query(geometry, predicate='contains_properly')
                                    if geometries[c].area > 0]:
                    parent_child.append((parent, child))
        last_child_id = None
        for (parent, child) in sorted(parent_child, key=lambda s: (s[1].id, s[0].geometry.area)):
            if child.id != last_child_id:
                child.add_parent(parent)
                last_child_id = child.id

    def __check_connection(self, shape: Shape) -> bool:
    #==================================================
        if 'Polygon' in shape.geometry.geom_type:
            if (line := self.__line_finder.get_line(shape)) is None:
                shape.properties['exclude'] = not settings.get('authoring', False)
                shape.properties['colour'] = 'yellow'
                return False
            shape.geometry = line
        shape.properties['shape-type'] = SHAPE_TYPE.CONNECTION
        shape.properties['type'] = 'line'  ## or 'line-dash'
        return True

    def classify(self) -> list[Shape]:
    #=================================
        for shape in self.__shapes:
            if shape.shape_type in [SHAPE_TYPE.COMPONENT, SHAPE_TYPE.CONTAINER]:
                if (label := self.__text_finder.get_text(shape)) is not None:
                    shape.properties['label'] = label
        return [s for s in self.__shapes if not s.exclude]

#===============================================================================

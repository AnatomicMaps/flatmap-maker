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

from mapmaker.shapes import Shape, SHAPE_TYPE
from mapmaker.utils import log

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

# SVG pixel space scaled to world metres
# These are based on the CVS bondgraph diagram

MAX_TEXT_VERTICAL_OFFSET = 5        # Between cluster baseline and baselines of text in the cluster
TEXT_BASELINE_OFFSET = -14.5        # From vertical centre of a component

#===============================================================================

class TextShapeCluster:
    def __init__(self, shape: Optional[Shape]=None):
        self.__shapes: list[Shape] = []
        self.__baselines: float = 0
        if shape is not None:
            self.add_shape(shape)

    @property
    def baseline(self) -> float:
        return self.__baselines/len(self.__shapes) if len(self.__shapes) else 0

    @property
    def shapes(self) -> list[Shape]:
        return self.__shapes

    def add_shape(self, shape: Shape):
        self.__shapes.append(shape)
        self.__baselines += shape.baseline

    def left_sort_shapes(self):
        self.__shapes.sort(key=lambda s: s.left)

#===============================================================================

class ShapeClassifier:
    def __init__(self, shapes: list[Shape], map_area: float, metres_per_pixel: float):
        self.__shapes = list(shapes)
        self.__shapes_by_type: DefaultDict[SHAPE_TYPE, list[Shape]] = defaultdict(list[Shape])
        self.__geometry_to_shape: dict[int, Shape] = {}
        self.__max_text_vertical_offset = metres_per_pixel * MAX_TEXT_VERTICAL_OFFSET
        self.__text_baseline_offset = metres_per_pixel * TEXT_BASELINE_OFFSET
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
                    shape.properties['shape-type'] = SHAPE_TYPE.CONNECTION
                    shape.properties['type'] = 'line'  ## or 'line-dash'
                elif bbox_coverage > 0.001 and coverage > 0.9:
                    shape.properties['shape-type'] = SHAPE_TYPE.CONTAINER
                elif bbox_coverage < 0.0005 and aspect > 0.9 and 0.7 < coverage <= 0.85:
                    shape.properties['shape-type'] = SHAPE_TYPE.COMPONENT
                elif bbox_coverage < 0.001 and coverage > 0.85:
                    shape.properties['shape-type'] = SHAPE_TYPE.COMPONENT
                else:
                    log.warning(f'Unclassifiable shape: {shape.id} {shape.properties.get('geometry')}')
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

    def classify(self) -> list[Shape]:
    #=================================
        for shape in self.__shapes:
            if shape.shape_type in [SHAPE_TYPE.COMPONENT, SHAPE_TYPE.CONTAINER]:
                self.__set_label(shape)
        return [s for s in self.__shapes if not s.exclude]

    def __set_label(self, shape: Shape):
    #===================================
        text_shapes = [s for s in shape.children if s.shape_type == SHAPE_TYPE.TEXT]
        text_clusters = self.__cluster_text(text_shapes)
        text_baseline = (shape.geometry.bounds[1] + shape.geometry.bounds[3])/2 + self.__text_baseline_offset
        base_text = superscript = subscript = ''
        for cluster in text_clusters:
            if (cluster.baseline + self.__max_text_vertical_offset) < text_baseline:
                subscript = self.__text_block_to_text(cluster.shapes)
            elif (cluster.baseline - self.__max_text_vertical_offset) > text_baseline:
                superscript = self.__text_block_to_text(cluster.shapes)
            else:
                base_text = self.__text_block_to_text(cluster.shapes)
        label = f'${base_text}{f"_{{{subscript}}}" if subscript != "" else ""}{f"^{{{superscript}}}" if superscript != "" else ""}$'
        if label != '':
            shape.properties['label'] = label

    def __text_block_to_text(self, text_block: list[Shape]) -> str:
    #==============================================================
        return f'{''.join([s.text for s in text_block])}'.replace(' ', '\\ ')

    def __cluster_text(self, text_shapes: list[Shape]) -> list[TextShapeCluster]:
    #============================================================================
        baseline_ordered_shapes = sorted(text_shapes, key=lambda s: s.baseline)
        clusters: list[TextShapeCluster] = []
        current_cluster = None
        for shape in baseline_ordered_shapes:
            if (current_cluster is None
             or (shape.baseline - current_cluster.baseline) > self.__max_text_vertical_offset):
                current_cluster = TextShapeCluster(shape)
                clusters.append(current_cluster)
            else:
                # Note: ``current_cluster.baseline`` is monotonically increasing
                current_cluster.add_shape(shape)
            shape.properties['exclude'] = True
        for cluster in clusters:
            cluster.left_sort_shapes()
        return clusters

#===============================================================================

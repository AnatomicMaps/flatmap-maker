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
MAX_CHAR_SPACING    = 40000
MAX_VERTICAL_OFFSET = 50000

#===============================================================================

class ShapeClassifier:
    def __init__(self, shapes: list[Shape], map_area: float):
        self.__shapes = list(shapes)
        self.__shapes_by_type: DefaultDict[SHAPE_TYPE, list[Shape]] = defaultdict(list[Shape])
        self.__geometry_to_shape: dict[int, Shape] = {}
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
                    print(f'Unclassified shape: {shape.id} {shape.properties}')
                    shape.properties['exclude'] = True

            if not shape.properties.get('exclude', False):
                self.__shapes_by_type[shape.shape_type].append(shape)
                if shape.shape_type != SHAPE_TYPE.TEXT:
                    self.__geometry_to_shape[id(shape.geometry)] = shape
                    geometries.append(shape.geometry)

        self.__str_index = shapely.strtree.STRtree(geometries)
        self.__geometries: list[BaseGeometry] = self.__str_index.geometries     # type: ignore

    def classify(self) -> list[Shape]:
    #=================================
        parent_child = []
        for geometry in self.__geometries:
            if geometry.area > 0:
                parent = self.__geometry_to_shape[id(geometry)]
                for child in [self.__get_shape(c)
                                for c in self.__str_index.query(geometry, predicate='contains_properly')
                                    if self.__geometries[c].area > 0]:
                    parent_child.append((parent, child))
        last_child_id = None
        for (parent, child) in sorted(parent_child, key=lambda s: (s[1].id, s[0].geometry.area)):
            if child.id != last_child_id:
                child.add_parent(parent)
                last_child_id = child.id

        text_blocks = self.__block_text()
        for block in text_blocks.values():
            shape = self.__text_block_to_shape(block)
            print(shape.text)
            self.__shapes.append(shape)


        for shape in self.__shapes_by_type[SHAPE_TYPE.CONNECTION]:
            # Exclude connection interactivity -- lines will show in rasteriesed layer
            shape.properties['exclude'] = True

        return self.__shapes


    def __block_text(self) -> DefaultDict[int, list[Shape]]:
    #=======================================================
        block_number = 0
        text_blocks: DefaultDict[int, list[Shape]] = defaultdict(list[Shape])
        text_shapes = self.__shapes_by_type[SHAPE_TYPE.TEXT]
        text_shape_count = len(text_shapes)
        start_pos = 0
        while start_pos < text_shape_count:
            shape = text_shapes[start_pos]
            left_side = shape.left
            right_side = shape.right
            baseline = shape.baseline
            text_blocks[block_number].append(shape)
            pos = start_pos + 1
            while pos < text_shape_count:
                shape = text_shapes[pos]
                if (abs(baseline-shape.baseline) < MAX_VERTICAL_OFFSET
                 and shape.left < (right_side + MAX_CHAR_SPACING)
                 and shape.right > left_side):
                    left_side = shape.left
                    right_side = shape.right
                    text_blocks[block_number].append(shape)
                    pos += 1
                else:
                    block_number += 1
                    break
            start_pos = pos
        return text_blocks

    def __text_block_to_shape(self, text_block: list[Shape]) -> Shape:
    #=================================================================
        return Shape(None, shapely.unary_union([s.geometry for s in text_block]),
            shape_type = SHAPE_TYPE.TEXT,
            text=''.join([s.text for s in text_block]),
            label=f'${''.join([s.text for s in text_block])}$'.replace(' ', '\\ ')
        )

    def __cluster_text(self) -> DefaultDict[int, list[Shape]]:
    #=========================================================
        ordered_text: list[Shape] = sorted(self.__shapes_by_type[SHAPE_TYPE.TEXT], key=lambda s: (s.left, s.baseline))
        cluster_number = 0
        clusters = defaultdict(list[Shape])
        if len(ordered_text):
            shape = None
            start_index = 0
            while start_index < len(ordered_text):
                while (start_index < len(ordered_text)
                   and (shape := ordered_text[start_index]) is None):
                    start_index += 1
                if shape is not None:
                    clusters[cluster_number].append(shape)
                    ordered_text[start_index] = None      # type: ignore
                    baseline = shape.baseline
                    current_shape = shape
                    shape_index = start_index + 1
                    while shape_index < len(ordered_text):
                        while (shape_index < len(ordered_text)
                           and (shape := ordered_text[shape_index]) is None):
                            shape_index += 1
                        if shape is not None:
                            if shape.left - current_shape.right < MAX_CHAR_SPACING:
                                if abs(shape.baseline - baseline) < MAX_VERTICAL_OFFSET:
                                    clusters[cluster_number].append(shape)
                                    ordered_text[shape_index] = None      # type: ignore
                                    current_shape = shape
                                shape_index += 1
                            else:
                                start_index += 1
                                cluster_number += 1
                                break
        return clusters

    def __get_shape(self, index):
    #============================
        return self.__geometry_to_shape[id(self.__geometries[index])]

#===============================================================================

class TextClassifier:
    def __init__(self, text_shapes: list[Shape]):
        self.__ordered_text: list[Shape] = sorted(text_shapes, key=lambda s: (s.left, s.baseline))
        self.__text_size = len(self.__ordered_text)
        self.__text_shapes: list[Shape] = []
        pos = 0
        while (pos is not None
           and (text_row := self.__text_row(pos)) is not None):
            self.__text_shapes.append(Shape(None, text_row[1],
                label=f'${text_row[0]}$'.replace(' ', '\\ '),
                shape_type=SHAPE_TYPE.TEXT,
                text=text_row[0]
            ))
            pos = self.__shape_pos(pos + 1)

    @property
    def text_shapes(self) -> list[Shape]:
    #====================================
        return self.__text_shapes

    def __shape_pos(self, start_pos: int) -> Optional[int]:
    #======================================================
        while (start_pos < self.__text_size
           and self.__ordered_text[start_pos] is None):
            start_pos += 1
        if start_pos < self.__text_size:
            return start_pos
        return None

    def __text_row(self, start_pos: int, level=0, parent_baseline: Optional[float]=None) -> Optional[tuple[str, BaseGeometry, float]]:
    #============================================================================
        text: list[str] = []
        geometry: list[BaseGeometry] = []
        right_side: float = 0
        pos = self.__shape_pos(start_pos)
        if pos is not None:
            row_baseline = self.__ordered_text[pos].baseline
            shape = self.__ordered_text[pos]
            while pos is not None:
                if abs(row_baseline - shape.baseline) <= 0.1*MAX_VERTICAL_OFFSET:
                    if (block := self.__text_block(pos, level, parent_baseline)) is not None:
                        text.append(block[0])
                        geometry.append(block[1])
                        right_side = block[2]
                        if block[0].endswith(')'):
                            break
                pos = self.__shape_pos(pos+1)
                if pos is not None:
                    shape = self.__ordered_text[pos]
                    if (shape.left - right_side) > MAX_CHAR_SPACING:
                        break

        if len(text):
            return (''.join(text), shapely.unary_union(geometry), right_side)

    def __text_block(self, start_pos: int, level=0, parent_baseline: Optional[float]=None) -> Optional[tuple[str, BaseGeometry, float]]:
    #============================================================================
        pos = self.__shape_pos(start_pos)
        if pos is None:
            return None
        shape = self.__ordered_text[pos]
        text = [shape.text]
        geometry = [shape.geometry]
        baseline = shape.baseline
        if parent_baseline is None:
            parent_baseline = baseline
        right_side = shape.right
        self.__ordered_text[pos] = None           # type: ignore

        while (pos < self.__text_size
           and not text[-1].endswith(')')):
            while (pos < self.__text_size
               and ((shape := self.__ordered_text[pos]) is None
                 or (abs(baseline - shape.baseline) > MAX_VERTICAL_OFFSET/(level+1)
                 and abs(parent_baseline - shape.baseline) > 0.1*MAX_VERTICAL_OFFSET))):
                pos += 1
            if (pos >= self.__text_size
             or shape is None
             or abs(parent_baseline - shape.baseline) <= 0.1*MAX_VERTICAL_OFFSET
             or (shape.left - right_side) > MAX_CHAR_SPACING):
                break
            if shape.baseline > (baseline - 0.1*MAX_VERTICAL_OFFSET):
                if (superscript := self.__text_row(pos, level+1, baseline)) is not None:
                    text.append(f'^{{{superscript[0]}}}')
                    geometry.append(superscript[1])
                    right_side = superscript[2]
            elif shape.baseline < (baseline + 0.1*MAX_VERTICAL_OFFSET):
                if (subscript := self.__text_row(pos, level+1, baseline)) is not None:
                    text.append(f'_{{{subscript[0]}}}')
                    geometry.append(subscript[1])
                    right_side = subscript[2]
            else:
                text.append(shape.text)
                geometry.append(shape.geometry)
                right_side = shape.right
                self.__ordered_text[pos] = None   # type: ignore
            pos += 1
        return (''.join(text), shapely.unary_union(geometry), right_side)

#===============================================================================



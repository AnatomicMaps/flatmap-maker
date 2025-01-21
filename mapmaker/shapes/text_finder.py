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

from typing import Optional

#===============================================================================

from . import Shape, SHAPE_TYPE
from .constants import MAX_TEXT_VERTICAL_OFFSET, TEXT_BASELINE_OFFSET

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

class TextFinder:
    def __init__(self, scaling: float):
        self.__max_text_vertical_offset = scaling * MAX_TEXT_VERTICAL_OFFSET
        self.__text_baseline_offset = scaling * TEXT_BASELINE_OFFSET

    def get_text(self, shape: Shape) -> Optional[str]:
    #=================================================
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
        text = f'${base_text}{f"^{{{superscript}}}" if superscript != "" else ""}{f"_{{{subscript}}}" if subscript != "" else ""}$'
        return text if text != '' else None

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

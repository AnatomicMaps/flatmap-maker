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

import re
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
    def left(self) -> float:
        return self.__shapes[0].left

    @property
    def shapes(self) -> list[Shape]:
        return self.__shapes

    def add_shape(self, shape: Shape):
        self.__shapes.append(shape)
        self.__baselines += shape.baseline

    def left_sort_shapes(self):
        self.__shapes.sort(key=lambda s: s.left)

#===============================================================================

SUBSCRIPT_CHAR = '_'
SUPERSCRIPT_CHAR = '^'

#===============================================================================

class LatexMaker:
    def __init__(self):
        self.__latex = []
        self.__state = 0
        self.__subscripted = False
        self.__text = []

    @property
    def latex(self) -> str:
    #======================
        self.__make_latex()
        return ''.join(self.__latex)

    def add_text(self, text: str, state: int):
    #=========================================
        if state != self.__state:
            self.__make_latex()
            self.__state = state
        if text != '':
            self.__text.append(text)

    def __make_latex(self):
    #======================
        if len(self.__text):
            if self.__state < 0:
                self.__latex.append(f'{SUBSCRIPT_CHAR}{{{''.join(self.__text)}}}')
                self.__subscripted = True
            elif self.__state > 0:
                superscript = f'{SUPERSCRIPT_CHAR}{{{''.join(self.__text)}}}'
                if self.__subscripted:
                    self.__latex.insert(-1, superscript)
                else:
                    self.__latex.append(superscript)
            else:
                self.__latex.append(''.join(self.__text))
                self.__subscripted = False
            self.__text = []

#===============================================================================

class TextFinder:
    def __init__(self, scaling: float):
        self.__sub_superscript_re = re.compile(f'{SUBSCRIPT_CHAR}|\\{SUPERSCRIPT_CHAR}')
        self.__max_text_vertical_offset = scaling * MAX_TEXT_VERTICAL_OFFSET
        self.__text_baseline_offset = scaling * TEXT_BASELINE_OFFSET

    def get_text(self, shape: Shape) -> Optional[tuple[str, list[Shape]]]:
    #=====================================================================
        text_shapes = [s for s in shape.children if s.shape_type == SHAPE_TYPE.TEXT]
        text_clusters = self.__cluster_text(text_shapes)
        offset = self.__max_text_vertical_offset
        baseline = (shape.geometry.bounds[1] + shape.geometry.bounds[3])/2 + self.__text_baseline_offset
        state = 0
        clusters = []
        latex = LatexMaker()
        used_text_shapes = []
        for cluster in text_clusters:
            if cluster.baseline < (baseline - offset):
                if state > 0 and len(clusters):
                    latex.add_text(self.__text_clusters_to_text(clusters), state)
                    clusters = []
                clusters.append(cluster)
                state = -1
            elif cluster.baseline > (baseline + offset):
                if state < 0 and len(clusters):
                    latex.add_text(self.__text_clusters_to_text(clusters), state)
                    clusters = []
                clusters.append(cluster)
                state = 1
            else:
                if state != 0 and len(clusters):
                    latex.add_text(self.__text_clusters_to_text(clusters), state)
                    clusters = []
                latex.add_text(self.__text_block_to_text(cluster.shapes), 0)
                state = 0
            used_text_shapes.extend(cluster.shapes)
        if len(clusters):
            latex.add_text(self.__text_clusters_to_text(clusters), state)
        text = f'${text}$' if self.__sub_superscript_re.search(text:=latex.latex) is not None else text
        return (text, used_text_shapes) if text != '' else None

    def __text_block_to_text(self, text_block: list[Shape]) -> str:
    #==============================================================
        return f'{''.join([s.text for s in text_block])}'.replace(' ', '\\ ')

    def __text_clusters_to_text(self, text_clusters: list[TextShapeCluster]) -> str:
    #===============================================================================
        baseline = text_clusters[0].baseline
        offset = 0.9*self.__max_text_vertical_offset
        latex = LatexMaker()
        for cluster in text_clusters:
            if cluster.baseline < (baseline - offset):
                latex.add_text(self.__text_block_to_text(cluster.shapes), -1)
            elif cluster.baseline > (baseline + offset):
                latex.add_text(self.__text_block_to_text(cluster.shapes), 1)
            else:
                latex.add_text(self.__text_block_to_text(cluster.shapes), 0)
        return latex.latex

    def __cluster_text(self, text_shapes: list[Shape]) -> list[TextShapeCluster]:
    #============================================================================
        offset = self.__max_text_vertical_offset
        shapes_seen_order = sorted(text_shapes, key=lambda s: s.number)
        clusters: list[TextShapeCluster] = []
        current_cluster = None
        for shape in shapes_seen_order:
            if (current_cluster is None
             or abs(shape.baseline - current_cluster.baseline) > offset):
                current_cluster = TextShapeCluster(shape)
                clusters.append(current_cluster)
            else:
                current_cluster.add_shape(shape)
            shape.properties['exclude'] = True
        return clusters

#===============================================================================

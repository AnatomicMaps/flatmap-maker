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
from .constants import MAX_TEXT_VERTICAL_OFFSET, TEXT_BASELINE_OFFSET, TEXT_COMPONENT_HEIGHT

#===============================================================================

class TextShapeCluster:
    def __init__(self, shape: Optional[Shape]=None):
        self.__shapes: list[Shape] = []
        self.__baselines: float = 0
        if shape is not None:
            self.add_shape(shape)

    @property
    def baseline(self) -> float:
        return self.__shapes[0].baseline

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

CHEMICAL_SYMBOLS = {
    'Ca^{2+}': 'Ca2+',
    'CO_{2}': 'CO2',
    'Glc': 'Glc',
    'H_{2}O': 'H2O',
    'K^{+}': 'K+',
    'Na': 'Na',
    'Na^{+}': 'Na+',
    'O_{2}': 'O2',
}

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
        latex = ''.join(self.__latex)
        if (chem := CHEMICAL_SYMBOLS.get(latex)) is not None:
            latex = f'\\ce{{{chem}}}'
        return latex

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
        self.__latex_re = re.compile(f'{SUBSCRIPT_CHAR}|\\{SUPERSCRIPT_CHAR}|{{')
        self.__max_text_vertical_offset = scaling * MAX_TEXT_VERTICAL_OFFSET
        self.__text_baseline_offset = scaling * TEXT_BASELINE_OFFSET
        self.__shape_scaling = 1.0

    def get_text(self, shape: Shape) -> Optional[tuple[str, list[Shape]]]:
    #=====================================================================
        self.__shape_scaling = shape.height/TEXT_COMPONENT_HEIGHT
        text_shapes = [s for s in shape.children if s.shape_type == SHAPE_TYPE.TEXT]
        text_clusters = self.__cluster_text(text_shapes)
        if len(text_clusters) == 0:
            return None
        offset = self.__shape_scaling*self.__max_text_vertical_offset
        baseline = text_clusters[0].baseline
        state = 0
        clusters = []
        latex = LatexMaker()
        used_text_shapes = []
        if len(text_clusters) == 1:
            latex.add_text(self.__text_block_to_text(text_clusters[0].shapes), 0)
            used_text_shapes.extend(text_clusters[0].shapes)
        else:
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
        text = f'${text}$' if self.__latex_re.search(text:=latex.latex) else text.replace('\\ ', ' ')
        return (text, used_text_shapes) if text != '' else None

    def __text_block_to_text(self, text_block: list[Shape]) -> str:
    #==============================================================
        return f'{''.join([s.text for s in text_block])}'.replace(' ', '\\ ')

    def __text_clusters_to_text(self, text_clusters: list[TextShapeCluster]) -> str:
    #===============================================================================
        baseline = text_clusters[0].baseline
        offset = 0.9*self.__shape_scaling*self.__max_text_vertical_offset
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
        offset = self.__shape_scaling*self.__max_text_vertical_offset
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

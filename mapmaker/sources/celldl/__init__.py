#===============================================================================
#
#  Cell Diagramming Language
#
#  Copyright (c) 2018 - 2022  David Brooks
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
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

#===============================================================================

import shapely.geometry             # type: ignore
import shapely.strtree              # type: ignore

#===============================================================================

#===============================================================================

from mapmaker.flatmap.layers import MapLayer
from mapmaker.settings import settings
from mapmaker.utils import log

from .. import MapSource

from . import celldl
from .powerpoint import Powerpoint

#===============================================================================

# Map block colour to CellDL class
# TODO: get from a ``KEY`` block...
CELLDL_CLASS_COLOURS = {
    '#C5E0B4': celldl.FTU,      #  sub-ftu (e.g. RAGP in right atrium, Villi in digestive system wall FTU)
    '#E2F0D9': celldl.FTU,
    '#D0CECE': celldl.Organ,
    '#DCC5ED': celldl.CellType,
    '#93FFFF': celldl.Nerve,    # celltype.Nerve
}

CELLDL_PATH_COLOURS = {
    '#548235': 'para',          # celldl.Neuron.PARASYMPATHETIC
    '#FF0000': 'symp',          # celldl.Neuron.SYMPATHETIC
    '#4472C4': 'sensory',       # celldl.Neuron.SENSORY
}

CELLDL_ORDERED_PATHS = [
    'para',                     # celldl.Neuron.PARASYMPATHETIC
    'symp',                     # celldl.Neuron.SYMPATHETIC
]

#===============================================================================

@dataclass
class Feature:
    id: int
    geometry: shapely.geometry.base.BaseGeometry
    properties: Dict[str, str] = field(default_factory=dict)
    children: List[int] = field(default_factory=list, init=False)
    parent: int = field(default=-1, init=False)
    node: Tuple[int, list] = field(init=False)

    def __post_init__(self):
        self.node = (self.id, [])

    @property
    def colour(self):
        return self.properties.get('colour')

    @property
    def label(self):
        return self.properties.get('label', '')

    def is_celldl_class(self):
    #=========================
        return self.properties.get('colour') in CELLDL_CLASS_COLOURS

#===============================================================================

@dataclass
class Connector:
    id: str
    connection: Tuple[int, int]
    geometry: shapely.geometry.base.BaseGeometry
    properties: Dict[str, str] = field(default_factory=dict)

#===============================================================================

@dataclass
class Connection:
    id: str
    geometry: shapely.geometry.LineString
    properties: Dict[str, str] = field(default_factory=dict)
    organ_ids: Tuple[int] = field(default_factory=tuple)
    system_ids: Tuple[int] = field(default_factory=tuple)
    terminals: List[Feature] = field(default_factory=list)
    # type

#===============================================================================

class CellDlDiagram:
    def __init__(self, name, features, connectors):
        self.__features = features
        # Features with text that won't generate a CellDL object are annotations
        self.__annotation_ids = []
        # Top level features with text are CellDL ``Systems``
        self.__system_ids = []
        for id, feature in features.items():
            if id > 0:
                if feature.label != '' and not feature.is_celldl_class():
                    if feature.colour is not None and feature.parent == 0:
                        self.__system_ids.append(id)
                    elif feature.parent > 0:
                        self.__annotation_ids.append(id)
                        self.__features[feature.parent].children.remove(id)

        self.__objects = {}
        self.__root_node = (0, [])
        self.__diagram = celldl.Diagram(name, 0)
        with self.__diagram:
            self.__add_children(self.__root_node, self.__system_ids)

        self.__connections = []
        for connector in connectors:
            start_ids = self.__ids_to_object(connector.connection[0])
            end_ids = self.__ids_to_object(connector.connection[1])
            ## This is the place to set path type from colour/dot(dash)
            self.__connections.append(Connection(connector.id, connector.geometry,
                properties=connector.properties,
                organ_ids=(self.__organ_id(start_ids[-1]), self.__organ_id(end_ids[-1])),
                system_ids=(self.__system_id(start_ids[-1]), self.__system_id(end_ids[-1])),
                terminals=[self.__features[id] for id in start_ids[:-1]]
                        + [self.__features[id] for id in end_ids[:-1]]
            ))

    # Find CellDL objects that connection is connected to by following parent
    # chain until we have an object
    def __ids_to_object(self, id):
    #=============================
        ids = []
        while id != 0 and id not in self.__objects:
            if id not in self.__annotation_ids:
                ids.append(id)
                ##self.__annotation_ids.remove(id)
            ## these ids/features are the terminal geometry of each end
            id = self.__features[id].parent
        ## error if id == 0
        ids.append(id)
        return ids

    @property
    def annotation_ids(self):
        return self.__annotation_ids

    @property
    def connections(self):
        return self.__connections

    @property
    def features(self):
        return self.__features

    @property
    def system_ids(self):
        return self.__system_ids

    def organ_ids(self, system_id):
        return self.__features[system_id].children

    def __organ_id(self, id):
        # organ has system parent which has parent == 0
        while (pid := self.__features[id].parent) != 0 and self.__features[pid].parent != 0:
            id = pid
        return id

    def __system_id(self, id):
        while self.__features[id].parent != 0:
            id = self.__features[id].parent
        return id

    def __add_children(self, parent_node, ids):
        for id in ids:
            feature = self.__features[id]
            if parent_node[0] == 0:
                CellDlClass = celldl.System
            else:
                CellDlClass = CELLDL_CLASS_COLOURS[feature.properties['colour']]
            if CellDlClass is not None:
                celldl_object = CellDlClass(feature.label, id)   ## Keep properties with CellDL object??
                feature.properties['celldl-class'] = celldl_object.CellDL_CLASS
                self.__objects[id] = celldl_object
                parent_node[1].append(feature.node)
                children = [child for child in feature.children
                            if self.__features[child].is_celldl_class()]
                if len(children):
                    self.__add_children(feature.node, children)


##
##  CellDL model
##  ============
##
##  * Nodes
##  * Tree structure of nodes
##      --> semantics
##      --> geometry + style
##  * Connections (between nodes)
##  * Annotation
##
##

    def __apply_to_node_feature(self, node, function):
        if node[0] != 0:
            function(self.__features[node[0]])
        for node in node[1]:
           self.__apply_to_node_feature(node, function)

    def apply_to_node_features(self, function):
    #============================================
        self.__apply_to_node_feature(self.__root_node, function)

    def apply_to_child_node_features(self, node, function):
    #======================================================
        for node in node[1]:
           self.__apply_to_node_feature(node, function)

#===============================================================================

class CellDlSource(MapSource):
    def __init__(self, flatmap, id, source_href):
        super().__init__(flatmap, id, source_href, 'celldl')
        ppt = Powerpoint(source_href)
        self.bounds = ppt.geometry.bounds
        self.__transform = ppt.transform
        self.__layer = CellDlLayer(id, self, ppt)
        self.add_layer(self.__layer)

    @property
    def transform(self):
        return self.__transform

    def process(self):
    #=================
        self.__layer.process()

#===============================================================================

class CellDlLayer(MapLayer):
    def __init__(self, id, source, ppt):
        super().__init__(id, source, exported=True)
        self.__ppt = ppt

    def process(self):
        connectors = []
        features = {}
        source_geometry = self.__ppt.geometry
        features[0] = Feature(0, source_geometry)
        geometries = [source_geometry]
        shape_ids = {id(source_geometry): 0}     # id(geometry) --> shape.id
        for shape in self.__ppt.process():
            shape_id = shape.id
            geometry = shape.geometry
            if shape.type == 'feature' and shape.geometry.geom_type == 'Polygon':
                geometries.append(geometry)
                shape_ids[id(geometry)] = shape_id
                features[shape_id] = Feature(shape_id, geometry, shape.properties)
            elif shape.type == 'connector':
                start = shape.properties.pop('connection-start', None)
                end = shape.properties.pop('connection-end', None)
                if start is not None and end is not None:
                    connectors.append(Connector(shape_id, (start, end), geometry, shape.properties))
                else:
                    log.warning('Connector {} ({}) ignored -- ends are missing: {} --> {}'
                                .format(shape_id, shape.properties['shape-name'], start, end))
        idx = shapely.strtree.STRtree(geometries)
        for shape_id, feature in features.items():
            if shape_id > 0:     # features[0] == entire slide
                intersecting_geometries = idx.query(feature.geometry)
                overlaps = [shape_ids[i[0]]
                                for i in sorted([(id(geometry), geometry.area)
                                                    for geometry in intersecting_geometries],
                                                key = lambda x: x[1])
                           ]
                parent_index = overlaps.index(shape_id) + 1
                # Exclude larger features we partially intersect
                while parent_index < len(overlaps) and not features[overlaps[parent_index]].geometry.contains(feature.geometry):
                    parent_index += 1
                parent_id = overlaps[parent_index]
                features[shape_id].parent = parent_id
                if parent_id > 0:
                    features[parent_id].children.append(shape_id)
        celldl = CellDlDiagram(self.id, features, connectors)


        # Go through self.__features creating flatmap features
        # and add them to the map.
        #
        #

        self.add_features('CellDl-features', [
            self.flatmap.new_feature(feature.geometry, feature.properties)
                for feature in celldl.features.values()],
            tile_layer='features')

        path_features = []
        for connection in celldl.connections:
            properties = connection.properties.copy()
            path_type = CELLDL_PATH_COLOURS.get(properties.get('colour'))
            if path_type is not None:
                if path_type in CELLDL_ORDERED_PATHS:
                    line_style = properties.pop('line-style', '').lower()
                    path_order = 'pre' if ('dot' in line_style or 'dash' in line_style) else 'post'
                    properties['kind'] = f'{path_type}-{path_order}'
                    properties['type'] = 'line-dash' if path_order == 'pre' else 'line'
                else:
                    properties['kind'] = path_type
                    properties['type'] = 'line'
            else:
                properties['type'] = 'line'
            path_features.append(self.flatmap.new_feature(connection.geometry, properties))
            for terminal in connection.terminals:
                terminal_properties = terminal.properties.copy()
                terminal_properties.update(properties)
                path_features.append(self.flatmap.new_feature(terminal.geometry, terminal_properties))
        self.add_features('CellDl-paths', path_features, tile_layer='pathways')

#===============================================================================

if __name__ == '__main__':
    settings['verbose'] = True

    celldl = CellDlSource()

    svg = celldl.output.SvgDrawing(ppt.geometry.bounds)
    svg.render(celldl_diagram)
    svg.save('ftu_test.svg', pretty_print=True)

    geojson = celldl.output.GeoJson(ppt.geometry.bounds)
    geojson.render(celldl_diagram)
    geojson.save('ftu_test.geojson', pretty_print=True)

    # One off to identify colours used by non-system blocks
    print_block_colours = False
    if print_block_colours:
        block_colours = set()
        for id, feature in features.items():
            if feature.label != '' and feature.colour is not None and feature.parent > 0:
                block_colours.add(feature.colour)
        pprint(block_colours)

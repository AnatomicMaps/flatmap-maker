#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2023  David Brooks
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

import math
from typing import Any

#===============================================================================

import networkx as nx
from shapely.geometry.linestring import LineString
from shapely.geometry.point import Point
import shapely.strtree

#===============================================================================

from mapmaker.sources import PATHWAYS_TILE_LAYER
from mapmaker.sources.shape import Shape, SHAPE_TYPE
from mapmaker.utils import log

from .components import FCComponent, FC_CLASS, FC_TYPE
from .components import CONNECTOR_PORT_CLASSES, CONNECTOR_SYMBOL_CLASSES
from .components import MAX_CONNECTION_GAP

#===============================================================================

def direction(coords):
    dx = coords[1][0] - coords[0][0]
    dy = coords[1][1] - coords[0][1]
    magnitude = math.hypot(dx, dy)
    return (dx/magnitude, dy/magnitude) if magnitude > 0 else None

def similar_direction(dirn_0, dirn_1):
    if dirn_0 is not None and dirn_1 is not None:
        # Within 30º of each other (1.93 is approx. sqrt(2 + sqrt(3)))
        return math.hypot(dirn_0[0] + dirn_1[0],
                          dirn_0[1] + dirn_1[1]) > 1.93
    return False

#===============================================================================

class Connections:
    __CONNECTOR_CLASSES = CONNECTOR_PORT_CLASSES + CONNECTOR_SYMBOL_CLASSES

    def __init__(self):
        self.__connection_graph = nx.Graph()
        self.__connectors_by_geometry = {}
        self.__connector_geometries = []
        self.__connector_index = None
        self.__join_nodes = []
        self.__metadata = {}
        self.__nerves_by_geometry = {}
        self.__nerve_geometries = []
        self.__nerve_index = None

    def as_dict(self):
    #=================
        connections = []
        for _, _, data in self.__connection_graph.edges(data=True):     # type: ignore
            connection = data['connection']                             # type: ignore
            connections.append({
                'id': connection.id,
                'ends': connection.connectors,
                'nerves': data['nerves']                                # type: ignore
                })
        return connections

    def add_component(self, component: FCComponent):   # Add component -- CONNECTOR, NERVE
    #===============================================
        if self.__connector_index is not None:         # .nerve_class  `join`, `in-plexus`
            log.error("Cannot add to connector index after it's been created")
        elif (component.fc_type == FC_TYPE.CONNECTOR
          and component.fc_class in self.__CONNECTOR_CLASSES):
            self.__connector_geometries.append(component.geometry)
            self.__connectors_by_geometry[id(component.geometry)] = component
            self.__add_connector_node(component)
        elif component.fc_type == FC_TYPE.NERVE:
            bounds = component.geometry.bounds
            # Use geometric mean of side lengths as a measure to determine if a connection
            # is alligned with the nerve
            component.properties['fc-long-side'] = math.sqrt((bounds[2]-bounds[0])**2 + (bounds[3]-bounds[1])**2)
            self.__nerve_geometries.append(component.geometry)
            self.__nerves_by_geometry[id(component.geometry)] = component

    def end_components(self):
    #========================
        if self.__connector_index is None:
            if len(self.__connector_geometries) == 0:
                log.warning('No components to connect to...')
            else:
                self.__connector_index = shapely.strtree.STRtree(self.__connector_geometries)
            self.__nerve_index = shapely.strtree.STRtree(self.__nerve_geometries)

    def __add_connector_node(self, connector):
    #=========================================
        self.__connection_graph.add_node(connector.id, connector=connector)

    def __closest_connector(self, point: Point):
    #===========================================
        if self.__connector_index is not None:
            closest_index = self.__connector_index.nearest(point)           # type: ignore
            closest_geometry = self.__connector_geometries[closest_index]   # type: ignore
            if closest_geometry.distance(point) < MAX_CONNECTION_GAP:
                return self.__connectors_by_geometry[id(closest_geometry)]

    def __crosses_nerves(self, connection: FCComponent):
    #===================================================
        nerve_ids = set()
        if self.__nerve_index is not None:
            for index in self.__nerve_index.query(connection.geometry):
                nerve_geometry = self.__nerve_geometries[index]
                nerve = self.__nerves_by_geometry[id(nerve_geometry)]
                if nerve_geometry.intersection(connection.geometry).length > nerve.properties['fc-long-side']:
                    nerve_ids.add(nerve.id)
        return nerve_ids

    def add_connection(self, connection: FCComponent):
    #=================================================
        assert connection.fc_class == FC_CLASS.NEURON
        unconnected = False
        nerve_ids = set()
        for coord_index in [0, -1]:
            end_point = Point(connection.geometry.coords[coord_index])
            if ((connector := self.__closest_connector(end_point)) is None
             or (connector.fc_class not in self.__CONNECTOR_CLASSES
              or connector.fc_class in CONNECTOR_PORT_CLASSES
             and not connection.nerve_class.startswith(connector.nerve_class))):
                ## Add a JOIN connector if the end point has no connector
                connector = FCComponent(Shape(SHAPE_TYPE.FEATURE, f'{connection.id}/{coord_index+1}', end_point.buffer(MAX_CONNECTION_GAP)))
                connector.fc_type = FC_TYPE.CONNECTOR
                connector.fc_class = FC_CLASS.FREE_END
                self.__add_connector_node(connector)
                unconnected = True
            connector_id = connector.id     # What will be added to the connector's list; will change if joining
            if connector.fc_class != FC_CLASS.PORT:
                if connector in self.__join_nodes:
                    ## But don't join pre/post ganglionic...
                    if len(neighbours := list(self.__connection_graph.neighbors(connector_id))) == 1:
                        join_connection = self.__connection_graph.edges[connector_id, neighbours[0]]['connection']
                        if join_connection.nerve_class.split('-')[0] != connection.nerve_class.split('-')[0]:
                            log.error(f'Connections cannot be joined: {connection} and {join_connection}')
                        elif join_connection.nerve_class == connection.nerve_class:
                            # Make sure the the connection ends being joined have the same direction
                            join0_coords = connection.geometry.coords
                            join1_coords = join_connection.geometry.coords
                            # From above:
                            #    end_point = Point(join0_coords[coord_index])
                            if coord_index == 0:
                                join0_dirn = direction(join0_coords[:coord_index+2])
                            else:
                                join0_dirn = direction(join0_coords[coord_index-1:])
                            if end_point.distance(Point(join1_coords[0])) < end_point.distance(Point(join1_coords[-1])):
                                if coord_index == 0:            # join_connection start + connection start
                                    join1_coords = list(reversed(join1_coords))
                                    join1_dirn = direction(join1_coords[-2:])
                                    coordinates = [join1_coords, list(join0_coords)]
                                else:                           # connection end + join_connection start
                                    join1_dirn = direction(join1_coords[:2])
                                    coordinates = [list(join0_coords), list(join1_coords)]
                            elif coord_index == 0:              # join_connection end + connection start
                                join1_dirn = direction(join1_coords[-2:])
                                coordinates = [list(join1_coords), list(join0_coords)]
                            else:                               # connection end + join_connection end
                                join1_coords = list(reversed(join1_coords))
                                join1_dirn = direction(join1_coords[:2])
                                coordinates = [list(join0_coords), join1_coords]
                            if similar_direction(join0_dirn, join1_dirn):   # Within 30 degrees
                                self.__join_nodes.remove(connector)
                                self.__connection_graph.remove_edge(connector.id, neighbours[0])
                                connection.set_geometry(LineString(coordinates[0]+coordinates[1]))
                                join_connection.properties['exclude'] = True
                                join_connection.connectors.remove(connector.id)
                                connector_id = join_connection.connectors.pop()
                    elif len(neighbours) > 1:
                        log.error(f'Connector has too many edges from it: {connector}')
                elif connector.fc_class != FC_CLASS.FREE_END:
                    self.__join_nodes.append(connector)
            connection.connectors.append(connector_id)
        if unconnected:
            log.warning(f'Connection has unconnected end(s): {connection} {connection.connectors}')

        ## Also get from properties['fc-parent'] if this identifies a NERVE

        nerve_ids.update(self.__crosses_nerves(connection))
        self.__connection_graph.add_edge(*connection.connectors, connection=connection, nerves=list(nerve_ids))

        # Map neuron path class to viewer path kind/type
        if '-' in connection.nerve_class:
            parts = connection.nerve_class.split('-', 1)
            connection.properties['kind'] = f'{parts[0][:4]}-{parts[1]}'
        else:
            connection.properties['kind'] = connection.nerve_class
        connection.properties['type'] = 'line-dash' if connection.properties['kind'].endswith('-pre') else 'line'
        connection.properties['shape-type'] = 'connection'
        connection.properties['shape-id'] = connection.shape.id
        connection.properties['tile-layer'] = PATHWAYS_TILE_LAYER

        #
        # PORTS have max 1 connection
        # THROUGHS have max 2 connections
        # NODES have max 2 connections
        # JOINS have max 2 connections
        #



    '''

    def __ftu_label(self, shape_id: str) -> str:
    #===========================================
        while self.__fc_features[shape_id].name == '':
            if shape_id == 0 or shape_id in self.__organs:
                break
            shape_id = self.__fc_features[shape_id].parents[0]
        return self.__fc_features[shape_id].label

    def __system_feature(self, shape_id: str) -> Optional[FCFeature]:
    #================================================================
        while shape_id != 0 and shape_id not in self.__systems:
            shape_id = self.__fc_features[shape_id].parents[0]
        return self.__fc_features[shape_id] if shape_id != 0 else None

    def __connector_node(self, shape_id: Optional[str]) -> Optional[tuple[Optional[str], str, FC_Class, list[str]]]:
    #===============================================================================================================
        if shape_id is not None:
            if (label := self.__ftu_label(shape_id)) != '':
                warnings: list[str] = []
                if ((colour := self.__fc_features[shape_id].colour) is None
                  or colour in self.__unknown_colours):
                    cls = None
                elif (cls := neuron_path_class(colour)) is None:
                    self.__unknown_colours.add(colour)
                    # NB. Some of these are for junction colours...
                    warnings.append(f'Colour {colour} is not a known connector class (shape {shape_id})')

                system = self.__system_feature(shape_id)
                if system is None:
                    # NB. 'Breasts' are in three systems but none are assigned...
                    warnings.append(f'Cannot determine system for connector {shape_id} in FTU {label}')

                return (cls, label, system.fc_class if system is not None else FC_Class.UNKNOWN, warnings)

    def __label_connectors(self):
    #============================
        for shape in self.shapes.flatten(skip=1):
            if shape.type == SHAPE_TYPE.CONNECTION:
                node_0 = self.__connector_node(shape.properties.get('connection-start', None))
                node_1 = self.__connector_node(shape.properties.get('connection-end', None))

                ## also check line colour...

#shape.colour
#shape.properties.get('line-style')
#shape.properties.get('head-end')
#shape.properties.get('tail-end')

                messages = shape.properties['messages']
                kind = 'unknown'   ### v's None
                label = ''
                if node_0 is not None and node_1 is not None:
                    messages.extend(node_0[3])
                    messages.extend(node_1[3])
                    kind = node_0[0]
                    if node_0[0] != node_1[0]:
                        if 'connector' not in [node_0[0], node_1[0]]:
                            messages.append(f'Ends of connector have different kinds: {[node_0[0], node_1[0]]}')
                        elif node_0[0] == 'connector':
                            kind = node_1[0]
                    if not node_0[2] == FC_Class.BRAIN and not node_1[2] == FC_Class.BRAIN:
                        messages.append(f'Connection is not to/or from the brain')
                        label = f'({node_0[1]}, {node_1[1]})'
                    elif node_0[2] == FC_Class.BRAIN:
                        if kind == 'sensory':
                            label = f'({node_1[1]}, {node_0[1]})'
                        else:
                            label = f'({node_0[1]}, {node_1[1]})'
                    elif kind == 'sensory':
                        label = f'({node_0[1]}, {node_1[1]})'
                    else:
                        label = f'({node_1[1]}, {node_0[1]})'
                elif node_0 is not None:
                    messages.extend(node_0[3])
                    kind = node_0[0]
                    if node_0[2] == FC_Class.BRAIN:
                        if kind == 'sensory':
                            label = f'(..., {node_0[1]})'
                        else:
                            label = f'({node_0[1]}, ...)'
                elif node_1 is not None:
                    messages.extend(node_1[3])
                    kind = node_1[0]
                    if node_1[2] == FC_Class.BRAIN:
                        if kind == 'sensory':
                            label = f'({node_1[1]}, ...)'
                        else:
                            label = f'(..., {node_1[1]})'
                # If there are warning messages then set ``kind`` to highlight
                # the connector and report the messages
                if kind == 'unknown':
                    messages.append('Unknown connector kind')   ## These needs to be on the connector, not connection...
                elif len(messages):
                    kind = 'error'
                if settings.get('authoring', False):
                    for warning in messages:
                        log.warning(warning)
                    if label:
                        messages.insert(0, label)
                    shape.properties['label'] = '\n'.join(messages)
                else:
                    for warning in messages:
                        log.warning(f'{warning}: {node_0[:3] if node_0 is not None else node_0}/{node_1[:3] if node_1 is not None else node_1}')
                    shape.properties['label'] = label
                if 'kind' not in shape.properties:
                    shape.properties['kind'] = kind
    '''

    '''
    def Xadd_connection(self, component: FCComponent):
        shape = component.shape
        shape.properties['messages'] = []
        shape_id = shape.id
        start_id = shape.properties.get('connection-start')
        end_id = shape.properties.get('connection-end')
        # Drop connections to features that aren't on the slide
        if start_id in self.__fc_features:
            self.__fc_features[start_id].kind |= FC.CONNECTED
            self.__connection_graph.add_node(start_id)    #### Include slide id with ppt id so connection_graph is over entire map...
        else:
            shape.properties['messages'].append(f'Connection {shape_id} is not connected to a start node: {shape.kind}/{shape.name}')
            shape.properties['connection-start'] = None
            shape.properties['kind'] = 'error'
            start_id = None
        if end_id in self.__fc_features:
            self.__fc_features[end_id].kind |= FC.CONNECTED
            self.__connection_graph.add_node(end_id)
        else:
            shape.properties['messages'].append(f'Connection {shape_id} is not connected to an end node: {shape.kind}/{shape.name}')
            shape.properties['connection-end'] = None
            shape.properties['kind'] = 'error'
            end_id = None
        if start_id is not None and end_id is not None:
            self.__connection_graph.add_edge(start_id, end_id)


# Create a scipy.spatial.KDTree from the centre of each connector...
#       kd_tree = scipy.spatial.KDTree(data) # n x 2 array
#
# For each connection end at `pt` (tuple):
#       indices = kd_tree.query.query_ball_point(pt, (R,), return_sorted=True)
#
#       indices[0] is index of closest connector...

            ##' ' '

            # get connection ends -->  metadata
            ## This is for CellDL conversion, not rastering image layer
            ## And then CellDL conversion is now via FCSlide layer, and that's the place
            ## to set metadata...


## rdflib for layer/slide
## dump as metadata when saving...

 ##           if 'type' in pptx_shape.line.headEnd or 'type' in pptx_shape.line.tailEnd:          # type: ignore
 ##               svg_element.set_markers((marker_id(pptx_shape.line.headEnd, 'head'),            # type: ignore
 ##                                        None, marker_id(pptx_shape.line.tailEnd, 'tail')       # type: ignore
 ##                                      ))
            ## use markers for setting end dirn property

            ## cf. __label_connectors() below...

            ## ' ' '

            start_arrow = shape.properties.get('head-end', 'none') != 'none'
            end_arrow = shape.properties.get('tail-end', 'none') != 'none'
            if start_arrow and not end_arrow:
                start_id, end_id = end_id, start_id
                if start_id is not None:
                    shape.properties['connection-start'] = start_id
                if end_id is not None:
                    shape.properties['connection-end'] = end_id
                arrows = 1
            elif start_arrow and end_arrow:
                arrows = 2     ## Do we create two connections???
            elif not start_arrow and not end_arrow:
                arrows = 0
            else:
                arrows = 1

            line_style = shape.properties.get('line-style', '').lower()
            ganglionic = 'pre' if 'dot' in line_style or 'dash' in line_style else 'post'

            ## from feature
            ## feature.type = FC_TYPE.CONNECTION
            ## feature.
            if (cls := neuron_path_class(shape)) is not None:
                # Map neuron path class to viewer path kind/type
                cls = {'sympathetic': 'symp', 'parasympathetic': 'para'}.get(cls, cls)
                shape.properties['kind'] = f'{cls}-{ganglionic}' if cls in ['para', 'symp'] else cls
                shape.properties['type'] = 'line-dash' if shape.properties['kind'].endswith('-pre') else 'line'
            else:
                shape.properties['messages'].append(f'Connection {shape_id} has unknown colour: {shape.colour}')

            ### We need features and nerves that path traverses...

            self.__connections[shape.id] = Connection(shape.id, start_id, end_id, shape.geometry, arrows, shape.properties)

# ********               if start is None or end is None:
#                    ## Still add as connector but use colour/width to highlight
#                    log.warning('{} ends are missing: {} --> {}'
#                                .format(shape.properties['shape-name'], start, end))
#                elif arrows == 0:
#                    log.warning('{} has no direction'
# *********                                .format(shape.properties['shape-name']))

    '''

    def get_metadata(self) -> dict[str, Any]:
    #========================================
        return self.__metadata

    def circuit_graph(self) -> nx.Graph:
    #===================================
        # Find circuits
        seen_nodes = set()
        circuit_graph = nx.Graph()
        for (source, degree) in self.__connection_graph.degree():       # type: ignore
            if degree == 1 and source not in seen_nodes:
                circuit_graph.add_node(source)
                seen_nodes.add(source)
                for target, _ in nx.shortest_path(self.__connection_graph, source=source).items():  # type: ignore
                    if target != source and self.__connection_graph.degree(target) == 1:
                        circuit_graph.add_node(target)
                        circuit_graph.add_edge(source, target)
                        seen_nodes.add(target)
            elif degree >= 3:
                log.warning(f'Node {source}/{degree} is a branch point...')

        #print(self.__circuit_graph.edges)
        ##pprint(self.__seen_shape_kinds)
        ##print('Area', self.__smallest_shape_area)

        return circuit_graph

#===============================================================================

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
import svgelements

#===============================================================================

from mapmaker.knowledgebase.celldl import CD_CLASS, FC_CLASS, FC_KIND
from mapmaker.knowledgebase.sckan import PATH_TYPE
from mapmaker.settings import settings
from mapmaker.sources.shape import Shape, SHAPE_TYPE
from mapmaker.utils import log

from .components import is_component, is_connector, make_connector, system_ids
from .components import NEURON_PATH_TYPES, VASCULAR_KINDS
from .components import MAX_CONNECTION_GAP

#===============================================================================

STROKE_WIDTH_SCALE_FACTOR = 1270.0

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

class ConnectionGraph:
    def __init__(self):
        self.__connection_graph = nx.Graph()
        self.__metadata = {}

    def add_connector(self, connector):
    #==================================
        self.__connection_graph.add_node(connector.global_shape.id, connector=connector)

    def add_connection(self, connection):
    #====================================
        if len(connection.connector_ids) == 2:
            self.__connection_graph.add_edge(*connection.connector_ids, connection=connection)

    def as_dict(self):
    #=================
        connections = []
        for n_0, n_1, data in self.__connection_graph.edges(data=True): # type: ignore
            connection = data['connection']                             # type: ignore
            connections.append({
                'id': connection.id,
                'connectors': (n_0, n_1)
                })
        return connections

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
        return circuit_graph

    def edge(self, node_0, node_1):
    #==============================
        return self.__connection_graph.edges[node_0, node_1]

    def get_metadata(self) -> dict[str, Any]:
    #========================================
        return self.__metadata

    def neighbors(self, node):
    #=========================
        return self.__connection_graph.neighbors(node)

    def remove_edge(self, node_0, node_1):
    #=====================================
        self.__connection_graph.remove_edge(node_0, node_1)

#===============================================================================

INTERMEDIATE_CONNECTORS = [
    FC_KIND.CONNECTOR_NODE,
    FC_KIND.GANGLION,
    FC_KIND.PLEXUS
]

JOINING_CONNECTORS = [
    FC_KIND.CONNECTOR_JOINER,
    FC_KIND.CONNECTOR_NODE,
    FC_KIND.GANGLION,
    FC_KIND.PLEXUS
]

NODE_CONNECTORS = [
    FC_KIND.CONNECTOR_NODE,
    FC_KIND.CONNECTOR_PORT,
    FC_KIND.GANGLION
]

#===============================================================================

class ConnectionClassifier:
    def __init__(self):
        self.__neural_graph = ConnectionGraph()
        self.__vascular_graph = ConnectionGraph()
        self.__connectors = {}
        self.__connector_ids_by_geometry = {}
        self.__connector_geometries = []
        self.__connector_index = None
        self.__join_nodes = []
        self.__components_by_geometry = {}
        self.__component_geometries = []
        self.__component_index = None

    def as_dict(self):
    #=================
        return {
            'neural': self.__neural_graph.as_dict(),
            'vascular': self.__vascular_graph.as_dict()
        }

    def add_component(self, component: Shape):
    #=========================================
        if self.__component_index is not None:
            log.error("Cannot add components once connections are added")
        elif is_component(component):
            bounds = component.geometry.bounds
            # Use geometric mean of side lengths as a measure to determine if a connection
            # is aligned with the nerve
            component.fc_mean_side = math.sqrt(abs((bounds[2]-bounds[0])*(bounds[3]-bounds[1])))
            self.__component_geometries.append(component.geometry)
            self.__components_by_geometry[id(component.geometry)] = component

    def add_connector(self, connector: Shape):
    #=========================================
        if self.__connector_index is not None:
            log.error("Cannot add connectors once connections are added")
        elif is_connector(connector):
            self.__connector_geometries.append(connector.geometry)
            self.__connector_ids_by_geometry[id(connector.geometry)] = connector.id
            self.__add_connector_node(connector)

    def __add_connector_node(self, connector):
    #=========================================
        self.__connectors[connector.id] = connector
        if connector.fc_class == FC_CLASS.NEURAL:
            self.__neural_graph.add_connector(connector)
        elif connector.fc_class == FC_CLASS.VASCULAR:
            self.__vascular_graph.add_connector(connector)

    def __check_indexes(self, connection):
    #=====================================
        if self.__component_index is None:
            if len(self.__component_geometries) == 0:
                connection.log_warning(f'No components to connect to: {connection}')
            else:
                self.__component_index = shapely.strtree.STRtree(self.__component_geometries)
        if self.__connector_index is None:
            if len(self.__connector_geometries) == 0:
                connection.log_warning(f'No connectors to connect to {connection}')
            else:
                self.__connector_index = shapely.strtree.STRtree(self.__connector_geometries)

    def __closest_connector_id(self, point: Point):
    #==============================================
        if self.__connector_index is not None:
            closest_index = self.__connector_index.nearest(point)           # type: ignore
            closest_geometry = self.__connector_geometries[closest_index]   # type: ignore
            if closest_geometry.distance(point) < MAX_CONNECTION_GAP:
                return self.__connector_ids_by_geometry[id(closest_geometry)]

    def __crossed_component(self, connection: Shape):
    #================================================
        component_ids = set()
        if self.__component_index is not None:
            for index in self.__component_index.query(connection.geometry):
                component_geometry = self.__component_geometries[index]
                component = self.__components_by_geometry[id(component_geometry)]
                if (connection.fc_class == component.fc_class
                and component_geometry.intersection(connection.geometry).length > component.fc_mean_side):
                    component_ids.add(component.global_shape.id)
        return component_ids

    def add_connection(self, connection: Shape):
    #===========================================
        self.__check_indexes(connection)

        # First find connectors at the end of the connection
        connected_end_ids = []
        free_end_connectors = []
        connection_end_index = {}
        for coord_index in [0, -1]:
            end_point = Point(connection.geometry.coords[coord_index])
            if (connector_id := self.__closest_connector_id(end_point)) is not None:
                connected_end_ids.append(connector_id)
            else:
                ## Add a JOIN connector if the end point has no connector
                connector_id = f'{connection.id}/{coord_index+1}'
                connector = make_connector(Shape(SHAPE_TYPE.FEATURE, connector_id,
                                                 end_point.buffer(MAX_CONNECTION_GAP), {
                                                    'colour': connection.colour,
                                                    'fc-class': connection.fc_class,
                                                    'fc-kind':FC_KIND.CONNECTOR_FREE_END
                                                }))
                free_end_connectors.append(connector)
            connection_end_index[connector_id] = coord_index

        # Check end of connection in Powerpoint is as expected
        def check_powerpoint_connection_end(end_attribute):
            if (connector_id := connection.properties.get(end_attribute)) is not None:
                if connector_id not in self.__connectors:
                    connection.log_warning(f'End of Powerpoint connection is unknown, connector: {connector_id}')
                elif connector_id not in connected_end_ids:
                    connection.log_warning(f"End of Powerpoint connection isn't at end, connector: {connector_id}")
                else:
                    return
        check_powerpoint_connection_end('connection-start')
        check_powerpoint_connection_end('connection-end')

        # Warn when we can't find both ends of a connection
        if len(free_end_connectors):          ## Diaphram dashed line...??
            connection.log_warning(f'Connection has unconnected end(s): {connection.id}')
            if len(free_end_connectors) == 1:
                free_end_connectors[0].fc_class = self.__connectors[connected_end_ids[0]].fc_class
            for connector in free_end_connectors:
                self.__add_connector_node(connector)
                connected_end_ids.append(connector.id)

        connection.connector_ids.extend([self.__connectors[id].global_shape.id
                                            for id in connected_end_ids])      # Only compatible connectors??
        connection.local_connector_ids.extend(connected_end_ids)

        connector = self.__connectors[connected_end_ids[0]]
        connector_1 = self.__connectors[connected_end_ids[1]]

        connection_logger = (connection.log_warning if settings.get('invalidNeurons', False)
                        else connection.log_error)

        if connector.fc_class != connector_1.fc_class:
            connection_logger(f"Connection ends aren't compatible ({connector.fc_class} != {connector_1.fc_class})")

        connection.fc_class = connector.fc_class

        # Only add drawn connections if not using NPO connectivity
        if connection.fc_class == FC_CLASS.NEURAL and settings.get('NPO', False):
            connection.set_property('exclude', True)
            return

        if connection.fc_class == FC_CLASS.NEURAL:
            connection.fc_kind = FC_KIND.NEURON
            if (path_type := NEURON_PATH_TYPES.lookup(connection.colour)) is not None:
                if connector.fc_kind in NODE_CONNECTORS and path_type != connector.path_type:
                    connection_logger(f"Connection {connection.id}'s type doesn't match connector's: `{path_type.name}` != `{connector.path_type.name}`")
                if path_type in [PATH_TYPE.PARASYMPATHETIC, PATH_TYPE.SYMPATHETIC]:
                    line_style = connection.get_property('line-style', '').lower()
                    path_type |= (PATH_TYPE.PRE_GANGLIONIC if 'dot' in line_style or 'dash' in line_style
                             else PATH_TYPE.POST_GANGLIONIC)
                connection.path_type = path_type
                path_kind = path_type.viewer_kind
                connection.set_property('kind', path_kind)
                connection.set_property('type', 'line-dash' if path_kind.endswith('-post') else 'line')
            else:
                connection_logger(f"Connection colour ({connection.colour}) isn't a neuron type")
            connection.set_property('stroke-width', 1.0)
        elif connection.fc_class == FC_CLASS.VASCULAR:
            connection.description = VASCULAR_KINDS.lookup(connection.colour)       # type: ignore
            if (connector.fc_kind in NODE_CONNECTORS
            and connection.description != connector.description):
                connection_logger(f"Connection colour doesn't match connector's {connection.colour} != {connector.colour}")
            connection.set_property('kind', connection.description)
            connection.set_property('type', 'line')
            connection.set_property('stroke-width', connection.get_property('stroke-width',
                                                                            STROKE_WIDTH_SCALE_FACTOR)/STROKE_WIDTH_SCALE_FACTOR)
        if connection.fc_class == FC_CLASS.NEURAL:
            # Attempt to join neuron segments
            for connector_id in connected_end_ids:
                connector = self.__connectors[connector_id]
                if connector.fc_kind in JOINING_CONNECTORS:
                    if connector not in self.__join_nodes:
                        self.__join_nodes.append(connector)
                    else:
                        if len(neighbours := list(self.__neural_graph.neighbors(connector_id))):
                            # This is assuming we have two ends to the connection we are joining to.....
                            join_connection = self.__neural_graph.edge(connector_id, neighbours[0])['connection']
                            if join_connection.path_type == connection.path_type:   # Both will be pre- or post-
                                # Make sure the the connection ends being joined have the same direction
                                join0_coords = connection.geometry.coords
                                coord_index = connection_end_index[connector_id]
                                end_point = Point(join0_coords[coord_index])
                                if coord_index == 0:
                                    join0_dirn = direction(join0_coords[:coord_index+2])
                                else:
                                    join0_dirn = direction(join0_coords[coord_index-1:])
                                join1_coords = join_connection.geometry.coords
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
                                    self.__neural_graph.remove_edge(connector.global_shape.id, neighbours[0])
                                    if connector.fc_kind == FC_KIND.CONNECTOR_JOINER:
                                        connector.set_property('exclude', True)
                                    elif connector.fc_kind in INTERMEDIATE_CONNECTORS:
                                        connection.intermediate_connectors.append(connector.global_shape.id)
                                    join_connection.set_property('exclude', True)
                                    self.__join_nodes.remove(connector)
                                    path_coords = coordinates[0]+coordinates[1]
                                    connection.geometry = LineString(path_coords)
                                    # Update SVG representation of the path
                                    svg_path = svgelements.Path()
                                    svg_path.move(*path_coords)
                                    connection.properties['svg-element'] = svg_path
                                    # Want the connection's new end connector to be the end of the join_connection
                                    join_connection.connector_ids.remove(connector.global_shape.id)
                                    connection.connector_ids.remove(connector.global_shape.id)
                                    connection.connector_ids.append(join_connection.connector_ids.pop())
                                    # Need both local and global connector identifiers
                                    join_connection.local_connector_ids.remove(connector.id)
                                    connection.local_connector_ids.remove(connector.id)
                                    connection.local_connector_ids.append(join_connection.local_connector_ids.pop())
                                #else:
                                ### This means that there isn't an outgoing connection at the join
                                ### amd needs some warning, but can only detect this after **all**
                                ### connections have been processed.

                        elif len(neighbours) > 1:
                            connection_logger(f'Connector has too many edges from it: {connector}')

            connection.set_property('connectors', [self.__connectors[id] for id in connection.local_connector_ids])
            systems = set()
            for connector in connection.get_property('connectors'):
                systems.update(system_ids(connector))
            connection.set_property('system-ids', systems)

        connection.intermediate_components = list(self.__crossed_component(connection))
        if connection.fc_class == FC_CLASS.NEURAL:
            self.__neural_graph.add_connection(connection)
        elif connection.fc_class == FC_CLASS.VASCULAR:
            self.__vascular_graph.add_connection(connection)

        ## Also get from properties['fc-parent'] if this identifies a NERVE

        # PORTS have max 1 connection
        # THROUGHS have max 2 connections
        # NODES have max 2 connections
        # JOINS have max 2 connections

#===============================================================================

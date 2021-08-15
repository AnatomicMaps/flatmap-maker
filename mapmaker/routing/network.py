#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020  David Brooks
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

"""
File doc...
"""

#===============================================================================

import itertools

import beziers.path
import networkx as nx
import numpy as np
import shapely.geometry

#===============================================================================

from mapmaker.geometry import bezier_sample
from mapmaker.settings import settings
from mapmaker.utils import log

#===============================================================================

"""
Find the subgraph G' induced on G, that
1) contain all nodes in a set of nodes V', and
2) is a connected component.

See: https://stackoverflow.com/questions/58076592/python-networkx-connect-subgraph-with-a-loose-node
"""

def get_connected_subgraph(graph, v_prime):
#==========================================
    """Given a graph G=(V,E), and a vertex set V', find the V'', that
    1) is a superset of V', and
    2) when used to induce a subgraph on G forms a connected component.

    Arguments:
    ----------
    G : networkx.Graph object
        The full graph.
    v_prime : list
        The chosen vertex set.

    Returns:
    --------
    v_prime_prime : set
        The set of nodes fullfilling criteria 1) and 2).

    """
    vpp = set()
    for source, target in itertools.combinations(v_prime, 2):
        paths = nx.all_shortest_paths(graph, source, target)
        for path in paths:
            vpp = vpp.union(path)
    return vpp

#===============================================================================

class RouteSegment(object):
    def __init__(self, path_id, node_set, nodes_geometry, edge_geometry, path_type):
        self.__id = path_id
        self.__node_set = node_set
        self.__nodes_geometry = nodes_geometry
        self.__edge_geometry = edge_geometry
        self.__path_type = path_type

    @property
    def id(self):
        return self.__id

    @property
    def node_set(self):
        return self.__node_set

    def geometry(self) -> shapely.geometry:
        """
        Returns:
            A ``LineString`` or ``MultiLineString`` object connecting the segment's nodes.
        """
        path_layout = settings.get('pathLayout', 'automatic')
        if path_layout == 'linear':
            return shapely.geometry.MultiLineString(
                [ shapely.geometry.LineString([ node.centroid for node in nodes ])
                    for nodes in self.__nodes_geometry ])
        elif path_layout == 'automatic':
            # Automatic routing magic goes in here...
            pass
        # Fallback is centreline layout
        path = beziers.path.BezierPath.fromSegments(self.__edge_geometry)
        return shapely.geometry.LineString(bezier_sample(path))

    def properties(self) -> dict:
        """
        Returns:
            Properties of the line string object connecting the segment's nodes.
        """
        return {
            'kind': self.__path_type,
            'type': 'line-dash' if self.__path_type.endswith('-post') else 'line',
            # this is were we could set flags to specify the line-end style.
            # --->   <---    |---   ---|    o---   ---o    etc...
            # See https://github.com/alantgeo/dataset-to-tileset/blob/master/index.js
            # and https://github.com/mapbox/mapbox-gl-js/issues/4096#issuecomment-303367657
        }

#===============================================================================

class NetworkRouter(object):
    """
    Route paths through a pre-defined geometric network.

    Networks are defined in terms of their topological connections and geometric
    structures and can be thought of as conduit networks through which individual
    wires are routed.

    Args:
        network_graph: a networkx.Graph specifying the network.

            TODO: UPDATE...

            Each network model is an item in this dictionary, in the form
            ``MODEL_ID: EDGE_DICT``, where ``EDGE_DICT`` is of the form
            ``EDGE_ID: NODE_LIST`` and specifies the nodes which an edge
            connects. Nodes are specified as a list of identifiers, ordered
            from start to end node, and including any intermediate nodes.

            An example showing part of the ``vagus`` network::

                'vagus': {
                    'n_1': ['brain_40', 'point_1'],
                    'n_5': ['point_1', 'skull_1', 'ganglion_1'],
                    'n_6': ['ganglion_1', 'skull_2'],
                    'n_7': ['ganglion_1', 'point_2', 'point_3'],
                }

        edges: a dictionary specifying the geometric paths of edges.

            The geometric paths of edges are specified by items of the
            form ``EDGE_ID: BEZIER_PATH``, where the path is an object
            of type ``beziers.cubicbezier.CubicBezier``.

        nodes: a dictionary specifying the geometric shapes of nodes.

            The geometric shape of nodes are specified by items of the
            form ``NODE_ID: SHAPE``, where the shape is specified by
            a ``shapely.geometry`` object.


    """
    def __init__(self, network_graph):
        self.__network_graph = network_graph

    def layout(self, model: str, connections: list, pathways: list) -> dict:
        """
        Layout paths for a model.

        Args:
            model: The identifier of the network model to use for path routing.

            connections: a list of connections which require routing.

                A connection is specified by a dictionary. It has an ``id`` and a
                list of ``pathways`` specifying the individual segments used for the
                connection.

                Example::

                    {
                        "id": "connection_1",
                        "pathways": [ "neuron_1", "neuron_6"]  # index into pathways
                    }

            pathways: a list of segments.

                A segment is specified by a dictionary. It has an ``id``, start and end
                nodes, a list of ``paths`` (edges) to follow, and a ``type``.

                Example::

                    {
                        "id": "neuron_1",
                        "start": "brain_40",        # index into self.__nodes
                        "end": "ganglion_1",        # index into self.__nodes
                        "paths": [ "n_1", "n_5" ],  # index into self.__networks and self.__edges
                        "type": "para-pre"
                    }

        Returns:
            A dictionary of ``RouteSegment``s which define the geometric path and
            properties of each connection.
        """
        network = self.__networks.get(model, {})
        route_segments = {}
        for pathway in pathways:
            nodes_list = [network.get(edge) for edge in pathway['paths']]
            node_set = set(nodes_list[0])
            for nodes in nodes_list[1:]:
                node_set.update(nodes)
            if pathway['start'] != nodes_list[0][0]:
                log.error("Start node doesn't match path start for '{}'".format(pathway['id']))
            if pathway['end'] != nodes_list[-1][-1]:
                log.error("End node doesn't match path end for '{}'".format(pathway['id']))
            route_segments[pathway['id']] = RouteSegment(pathway['id'], node_set,
                                                         [[self.__nodes.get(node) for node in nodes]
                                                            for nodes in nodes_list],
                                                         [e for e in [self.__edges.get(edge)
                                                            for edge in pathway['paths']] if e is not None],
                                                         pathway['type'])

        return { connection['id']: [ route_segments.get(pathway)
                                        for pathway in connection['pathways']]
            for connection in connections}

#===============================================================================

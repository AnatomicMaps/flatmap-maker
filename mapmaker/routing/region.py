# ===============================================================================
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
# ===============================================================================

from beziers.cubicbezier import CubicBezier
from math import pi
import mercantile
from itertools import tee

#===============================================================================

import networkx as nx

#===============================================================================

from mapmaker.routing.utils.maths import add
from mapmaker.routing.utils.maths import magnitude
from mapmaker.routing.utils.maths import mult
from mapmaker.routing.utils.maths import normalize
from mapmaker.routing.utils.maths import set_magnitude
from mapmaker.routing.utils.maths import sub

# ===============================================================================

import matplotlib.pyplot as plt

# ===============================================================================


def get_geo_coordinates(x=None, y=None):
    x = 0.0 if None else x
    y = 0.0 if None else y
    return mercantile.lnglat(x, y)


def is_close(x: tuple, y: tuple, rel_tol=1e0, abs_tol=0.0) -> list:
    return [abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol) for a, b in (x, y)]


def pairwise(iterable):
    a, b = tee(iterable)
    next(b, None)
    return zip(a, b)


class Roads(object):

    def __init__(self, networks, edges, node_geometry):
        self.__networks = networks
        self.__edges = edges
        self.__node_geometry = node_geometry
        self.__node_coordinates = {}
        self.__node_derivatives = {}
        self.__graphs = {}
        self.__continuous_paths = {}
        self.__scaffold_settings = {}
        self.__continuous_centreline_scaffolds = {}
        self.__continuous_region_scaffolds = {}

    def build(self):
        self.__build_graphs()  # build a graph network for nerve sets
        self.__find_continuous_paths()  # find all possible paths from sources to targets
        self.__extract_components()  # get all the coordinates and derivatives
        self.__generate_2d_descriptions()
        print(" ")

    def __build_graphs(self):
        """
        Builds a dictionary of un-directed graph networks from a given map for every nerve set.
        """
        for nerve in self.__networks.keys():
            self.__graphs[nerve] = nx.Graph()  # creating individual graphs for each nerve
            for network in self.__networks.get(nerve):
                self.__graphs[nerve].add_edge(self.__networks[nerve][network][0],
                                              self.__networks[nerve][network][1],
                                              weight=1)

        """ to see the graph, uncomment the section below
        """
        # pos = nx.spring_layout(self.__graphs.get('vagus'))
        # nx.draw(self.__graphs.get('vagus'), pos, node_color='lawngreen', with_labels=True)
        # plt.axis('equal')
        # plt.show()

    def __find_continuous_paths(self):
        """
        Builds a dictionary of every possible paths from a source to target for every nerve set.
        Assumptions is that sources and targets have only 1 input/output (i.e, nodes with degree of 1). Any node with
        more than 1 degree are ignored and treated as branching/connecting node.
        """
        path_counter = 1
        for nerve in self.__networks.keys():
            self.__continuous_paths[nerve] = {}
            for network_source in self.__networks[nerve]:
                source = self.__networks[nerve][network_source][0]
                if self.__graphs[nerve].degree(source) > 1:
                    continue
                for network_target in self.__networks[nerve]:
                    target = self.__networks[nerve][network_target][1]
                    if self.__graphs[nerve].degree(target) > 1:
                        continue
                    else:
                        path = nx.shortest_path(self.__graphs.get(nerve), source=source, target=target)
                    self.__continuous_paths[nerve]['p_{}'.format(path_counter)] = path
                    path_counter += 1

    def __extract_components(self):
        """
        Extracts and stores network components (i.e., coordinates & derivatives) in a dictionary for every nerve set.
        Each nerve set is a dict with keys corresponding to the keys in self.__continuous_paths.
        """
        for nerve in self.__continuous_paths.keys():
            self.__node_coordinates[nerve] = {}
            self.__node_derivatives[nerve] = {}
            for network, path in self.__continuous_paths.get(nerve).items():
                self.__node_coordinates[nerve][network] = []
                self.__node_derivatives[nerve][network] = []
                if not isinstance(path, list):
                    path = [path]
                for point in path:
                    # get coordinates using the centroids of the geometry objects
                    x = self.__node_geometry[point].centroid.x
                    y = self.__node_geometry[point].centroid.y
                    x, y = get_geo_coordinates(x, y)
                    self.__node_coordinates[nerve][network].append((x, y))
                for p1, p2 in pairwise(path):
                    # get derivatives using the Bezier descriptions
                    segment = self.__get_segment_bezier(p1, p2)
                    dx1, dy1 = segment.derivative()[0].x, segment.derivative()[0].y
                    dx1, dy1 = get_geo_coordinates(dx1, dy1)
                    self.__node_derivatives[nerve][network].append((dx1, dy1))
                    if path.index(p2) == len(path) - 1:  # derivative of the last node
                        dx2, dy2 = segment.derivative()[-1].x, segment.derivative()[-1].y
                        dx2, dy2 = get_geo_coordinates(dx2, dy2)
                        self.__node_derivatives[nerve][network].append((dx2, dy2))

    def __get_segment_bezier(self, p1, p2):
        return [self.__edges[k] for k, v in self.__networks['vagus'].items() if v == [p1, p2]][-1]

    def __generate_2d_descriptions(self):
        scaffold_settings = {}
        for nerve in self.__continuous_paths.keys():
            self.__continuous_region_scaffolds[nerve] = {}
            scaffold_settings[nerve] = {}
            for network, _ in self.__continuous_paths.get(nerve).items():
                number_of_nodes = len(self.__continuous_paths.get(nerve).get(network))
                nodes = []
                d1 = []
                d2 = []
                for node_index in range(number_of_nodes):
                    x, y = self.__node_coordinates[nerve][network][node_index]
                    dx, dy = self.__node_derivatives[nerve][network][node_index]
                    normal_left = mult(normalize((dy, -dx)), 1)
                    normal_right = mult(normalize((-dy, dx)), 1)
                    new_node1 = [x + normal_left[0], y + normal_left[1]]
                    new_node2 = [x + normal_right[0], y + normal_right[1]]
                    nodes.append(new_node1)
                    nodes.append(new_node2)
                    d1.append(set_magnitude(normal_left, magnitude(normal_left) * 1))
                    d1.append(set_magnitude(normal_right, magnitude(normal_right) * 1))
                    d2.append([dx, dy])
                    d2.append([dx, dy])
                scaffold_settings[nerve] = {
                    'id': network,
                    'node coordinates': nodes,
                    'node derivatives 1': d1,
                    'node derivatives 2': d2,
                    'number of elements': number_of_nodes - 1
                }

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
from math import pi

from beziers.cubicbezier import CubicBezier

import mercantile

import networkx as nx

from .utils.maths import add
from .utils.maths import magnitude
from .utils.maths import mult
from .utils.maths import normalize
from .utils.maths import set_magnitude
from .utils.maths import sub


# ===============================================================================


def get_geo_coordinates(x=None, y=None):
    x = 0.0 if None else x
    y = 0.0 if None else y
    return mercantile.lnglat(x, y)


def is_close(x: tuple, y: tuple, rel_tol=1e0, abs_tol=0.0) -> list:
    return [abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol) for a, b in (x, y)]


class Roads(object):

    def __init__(self, networks, edges, node_geometry):
        self.__networks = networks
        self.__edges = edges
        self.__node_geometry = node_geometry
        self.__node_coordinates = {}
        self.__node_derivatives = {}
        self.__graphs = {}
        self.__continuous_paths = {}

        self.__extract_components()
        self.__build_graphs()
        self.__find_continuous_paths()

        print(" ")

    def __extract_components(self):
        """
        Extracts and stores network components (i.e., coordinates & derivatives) in a dictionary for every nerve set.
        """
        for nerve in self.__networks.keys():
            self.__node_coordinates[nerve] = {}
            for network, path in self.__networks.get(nerve).items():
                self.__node_coordinates[nerve][network] = []
                if not isinstance(path, list):
                    path = [path]
                for point in path:
                    # get coordinates using the centroids of the geometry objects
                    x = self.__node_geometry[point].centroid.x
                    y = self.__node_geometry[point].centroid.y
                    x, y = get_geo_coordinates(x, y)
                    self.__node_coordinates[nerve][network].append((x, y))
                    # get derivatives using the Bezier descriptions
                    # TODO: extract derivatives as well.

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

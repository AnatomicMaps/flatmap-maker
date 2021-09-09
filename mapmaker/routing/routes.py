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

from beziers.path import BezierPath
import mercantile

# ===============================================================================

import networkx as nx

# ===============================================================================

from mapmaker.utils import log
from mapmaker.routing.utils.pair_iteration import pairwise
from mapmaker.routing.utils.maths import magnitude
from mapmaker.routing.utils.maths import mult
from mapmaker.routing.utils.maths import normalize
from mapmaker.routing.utils.maths import set_magnitude
from mapmaker.routing.utils.maths import sub
from mapmaker.routing.utils.maths import add
from mapmaker.routing.utils.interpolation import smooth_cubic_hermite_derivatives_line as smooth_derivative
from mapmaker.routing.utils.interpolation import sample_cubic_hermite_curves as sample
from mapmaker.routing.scaffold_2d import Scaffold2dPath


# ===============================================================================

# import matplotlib.pyplot as plt

# ===============================================================================


def get_geo_coordinates(x=None, y=None):
    x = 0.0 if x is None else x
    y = 0.0 if y is None else y
    return mercantile.lnglat(x, y)


class Sheath(object):

    def __init__(self, path_network: nx.Graph, path_id):
        self.__path_network = path_network
        self.__id = path_id
        self.__edges = None
        self.__node_geometry = None
        self.__node_coordinates = {}
        self.__node_derivatives = {}
        self.__graphs = {}
        self.__continuous_paths = {}
        self.__scaffold_settings = {}
        self.__continuous_region_scaffolds = {}

        self._scaffold_test = {}

    def get_sheath(self, sources, targets) -> (dict, dict):
        path_index = []
        for source in sources:
            for target in targets:
                path = (nx.shortest_path(self.__path_network, source=source, target=target))
                for k, v in self.__continuous_paths.items():
                    if path == v:
                        path_index.append(k)
        sheaths = [self.__continuous_region_scaffolds[i] for i in path_index]
        derivatives = [self.__node_derivatives[i] for i in path_index]
        coordinates = [self.__node_coordinates[i] for i in path_index]
        settings = {'sheath_paths': sheaths,
                    'sheath_ids': path_index,
                    'derivatives': derivatives,
                    'coordinates': coordinates}
        return settings

    def build(self, sources, targets) -> None:
        log('Generating pathway scaffold layout...')
        # self.__check_for_middle_nodes()
        # self.__build_graphs()  # build a graph network for nerve sets
        self.__find_continuous_paths(sources, targets)  # find all possible paths from sources to targets
        self.__extract_components()  # get all the coordinates and derivatives
        # print(self.__node_derivatives)
        self.__generate_2d_descriptions()

        # def __check_for_middle_nodes(self):
        #     for nerve in self.__networks.keys():
        #         for network in self.__networks[nerve]:
        #             if len(self.__networks[nerve][network]) > 2:
        #                 self.__networks[nerve][network] = [self.__networks[nerve][network][0],
        #                                                    self.__networks[nerve][network][-1]]
        #
        # def __build_graphs(self) -> None:
        #     """
        #     Builds a dictionary of un-directed graph networks from a given map for every nerve set.
        #     """
        #     for nerve in self.__networks.keys():
        #         self.__graphs[nerve] = nx.Graph()  # creating individual graphs for each nerve
        #         for network in self.__networks.get(nerve):
        #             self.__graphs[nerve].add_edge(self.__networks[nerve][network][0],
        #                                           self.__networks[nerve][network][-1],
        #                                           weight=1)

        """ to see the graph, uncomment the section below
        """
        # pos = nx.spring_layout(self.__graphs.get('vagus'))
        # nx.draw(self.__graphs.get('vagus'), pos, node_color='lawngreen', with_labels=True)
        # plt.axis('equal')
        # plt.show()

    def __find_continuous_paths(self, sources, targets) -> None:
        """
        Builds a dictionary of every possible paths from a source to target for every nerve set.
        Assumptions is that sources and targets have only 1 input/output (i.e, nodes with degree of 1). Any node with
        more than 1 degree are ignored and treated as branching/connecting node.
        """

        segment_counter = 1
        for source in sources:
            for target in targets:
                path = (nx.shortest_path(self.__path_network, source=source, target=target))
                if path in self.__continuous_paths.values():
                    continue
                if len(path) < 2:
                    pass
                else:
                    self.__continuous_paths['p_{}'.format(segment_counter)] = path
                segment_counter += 1

    @staticmethod
    def __get_bezier_coefficients(segment):
        b0, b1, b2, b3 = segment.points[0], segment.points[1], segment.points[2], segment.points[3]
        b0, b1, b2, b3 = [b0.x, b0.y], [b1.x, b1.y], [b1.x, b1.y], [b1.x, b1.y]
        return b0, b1, b2, b3

    def __extract_components(self) -> None:
        """
        Extracts and stores network components (i.e., coordinates & derivatives) in a dictionary for every nerve set.
        Each nerve set is a dict with keys corresponding to the keys in self.__continuous_paths.

        """
        for network, path in self.__continuous_paths.items():
            self.__node_coordinates[network] = []
            self.__node_derivatives[network] = []
            if not isinstance(path, list):
                path = [path]
            for p1, p2 in pairwise(path):
                bezier, flipped = self.__has_centreline(p1, p2)
                if bezier is None:
                    x1 = self.__path_network.nodes(data='geometry')[p1].centroid.x
                    y1 = self.__path_network.nodes(data='geometry')[p1].centroid.y
                    self.__node_coordinates[network].append((x1, y1))  # assign node 1
                    x2 = self.__path_network.nodes(data='geometry')[p2].centroid.x
                    y2 = self.__path_network.nodes(data='geometry')[p2].centroid.y
                    # du = sub([x2, y2], [x1, y1])
                    du = [0., 0.]
                    if len(self.__node_derivatives[network]) < 1:  # use the mean derivatives
                        self.__node_derivatives[network].append((du[0] * 0.001, du[1] * 0.001))  # assign derivative 1
                    self.__node_derivatives[network].append((du[0] * 0.001, du[1] * 0.001))  # assign derivative 2
                    if path.index(p2) == len(path) - 1:  # if last node in the path:
                        self.__node_coordinates[network].append((x2, y2))  # assign last coordinate

                else:
                    segments = bezier.asSegments()
                    x1 = self.__path_network.nodes(data='geometry')[p1].centroid.x
                    y1 = self.__path_network.nodes(data='geometry')[p1].centroid.y
                    self.__node_coordinates[network].append((x1, y1))  # assign node 1

                    if len(segments) == 1:
                        segment = segments[-1]
                        b0, b1, b2, b3 = self.__get_bezier_coefficients(segment)
                        du = mult(sub(b1, b0), 3)
                        # if flipped:
                        #     du = mult(du, -1.)
                        if len(self.__node_derivatives[network]) > 1:  # use the mean derivatives
                            previous = self.__node_derivatives[network].pop()
                            du = mult(add(previous, du), 0.5)
                        self.__node_derivatives[network].append((du[0], du[1]))  # assign derivative 1
                        du2 = mult(sub(b3, b2), 3)
                        # if flipped:
                        #     du2 = mult(du2, -1.)
                        self.__node_derivatives[network].append((du2[0], du2[1]))  # assign derivative 2
                        if path.index(p2) == len(path) - 1:  # if last node in the path:
                            x2 = self.__path_network.nodes(data='geometry')[p2].centroid.x
                            y2 = self.__path_network.nodes(data='geometry')[p2].centroid.y
                            self.__node_coordinates[network].append((x2, y2))  # assign last coordinate
                    else:
                        counter = 0
                        for segment in segments:
                            b0, b1, b2, b3 = self.__get_bezier_coefficients(segment)
                            if counter > 0:
                                self.__node_coordinates[network].append(b0)
                            du = mult(sub(b1, b0), 3)
                            # if flipped:
                            #     du = mult(du, -1.)
                            if len(self.__node_derivatives[network]) > 1:  # use the mean derivatives
                                previous = self.__node_derivatives[network].pop()
                                du = mult(add(previous, du), 0.5)
                            self.__node_derivatives[network].append((du[0], du[1]))  # assign derivative 1
                            du2 = mult(sub(b3, b2), 3)
                            dx13, dy13 = segment.derivative()[2].x, segment.derivative()[2].y
                            self.__node_derivatives[network].append((dx13, dy13))  # assign derivative 2
                            counter += 1
                        if path.index(p2) == len(path) - 1:  # if last node in the path:
                            x2 = self.__path_network.nodes(data='geometry')[p2].centroid.x
                            y2 = self.__path_network.nodes(data='geometry')[p2].centroid.y
                            self.__node_coordinates[network].append((x2, y2))  # assign last coordinate

    def __has_centreline(self, p1: str, p2: str):
        for edge in self.__path_network.edges(data='geometry'):
            # print("edge0: ", edge[0], "; edge1: ", edge[1])
            if edge[2] is not None:
                if p1 in edge[0] and p2 in edge[1]:
                    return edge[2], False
                elif p2 in edge[0] and p1 in edge[1]:
                    return edge[2], True
            else:
                continue
        return None, None

    def __get_segment_bezier(self, p1: str, p2: str) -> BezierPath:
        # print(p1, '->', p2)
        for edge in self.__path_network.edges(data='geometry'):
            if p1 in edge and p2 in edge:
                return edge[2]

    def __generate_2d_descriptions(self) -> None:
        for network, path in self.__continuous_paths.items():
            # print(path)
            number_of_nodes = len(self.__node_coordinates[network])
            nodes = []
            d1 = []
            d2 = []
            node_coordinates = self.__node_coordinates[network]
            node_derivatives = self.__node_derivatives[network]

            # print("nodes: ", len(node_coordinates), "ders: ", len(node_derivatives))

            assert len(node_coordinates) == len(node_derivatives), \
                "routing.routes: Number of nodes & derivatives do not match."

            self.__node_coordinates[network], self.__node_derivatives[network], _, _, _ = sample(node_coordinates,
                                                                                                 node_derivatives,
                                                                                                 number_of_nodes*3)

            self.__node_derivatives[network] = smooth_derivative(self.__node_coordinates[network],
                                                                 self.__node_derivatives[network],
                                                                 fix_all_directions=False,
                                                                 fix_start_derivative=False,
                                                                 fix_end_derivative=False,
                                                                 fix_start_direction=False,
                                                                 fix_end_direction=False)
            number_of_nodes = len(self.__node_coordinates[network])
            for node_index in range(number_of_nodes):
                x, y = self.__node_coordinates[network][node_index]
                dx, dy = self.__node_derivatives[network][node_index]
                if dx == 0 or dy == 0:
                    normal_left = [1000, 1000]
                    normal_right = [1000, 1000]
                else:
                    normal_left = mult(normalize([dy, -dx]),
                                       1000)
                    normal_right = mult(normalize([-dy, dx]),
                                        1000)
                # TODO: find a way to properly adjust the normals so that the 2D nodes are created appropriately.
                # normal_left = mult(normalize([dy, -dx]),
                #                    self.__estimate_width(nerve, network, node_index) * 0.5)
                # normal_right = mult(normalize([-dy, dx]),
                #                     self.__estimate_width(nerve, network, node_index) * 0.5)
                new_node1 = [x + normal_left[0], y + normal_left[1]]
                nodes.append(new_node1)
                new_node2 = [x + normal_right[0], y + normal_right[1]]
                nodes.append(new_node2)
                d1.append(set_magnitude(normal_left, magnitude(normal_left) * 1.))
                d1.append(set_magnitude(normal_right, magnitude(normal_right) * 1.))
                d2.append([dx, dy])
                d2.append([dx, dy])

            scaffold_settings = {
                'id': network,
                'node coordinates': nodes,
                'node derivatives 1': d1,
                'node derivatives 2': d2,
                'number of elements': number_of_nodes - 1
            }
            scaffold = Scaffold2dPath(scaffold_settings)
            self.__continuous_region_scaffolds[network] = scaffold

    def __estimate_width(self, nerve: str, network: str, node_id: int) -> float:
        shape = self.__continuous_paths[nerve][network][node_id]
        shape_object = self.__node_geometry[shape]
        scale_x = get_geo_coordinates(shape_object.centroid.x, None)[0] / shape_object.centroid.x
        scale_y = get_geo_coordinates(None, shape_object.centroid.y)[1] / shape_object.centroid.y
        shape_rough_width = shape_object.length * ((scale_x + scale_y) / 2)
        return shape_rough_width

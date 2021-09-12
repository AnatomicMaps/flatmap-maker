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
from collections import defaultdict

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

#===============================================================================

class Sheath(object):
    def __init__(self, path_network: nx.Graph, path_id: str):
        self.__path_network = path_network
        self.__id = path_id
        self.__edges = None
        self.__node_geometry = None
        self.__node_coordinates = defaultdict(list)
        self.__node_derivatives = defaultdict(list)
        self.__graphs = {}
        self.__continuous_paths = {}
        self.__scaffold_settings = {}
        self.__continuous_region_scaffolds = {}

    def settings(self) -> dict:
    #==========================
        path_ids = list(self.__continuous_paths)
        scaffolds = [self.__continuous_region_scaffolds[i] for i in path_ids]
        derivatives = [self.__node_derivatives[i] for i in path_ids]
        coordinates = [self.__node_coordinates[i] for i in path_ids]
        settings = {'scaffolds': scaffolds,
                    'path_ids': path_ids,
                    'derivatives': derivatives,
                    'coordinates': coordinates}
        return settings

    def build(self, sources, targets) -> None:
        log('Generating pathway scaffold layout...')
        # self.__check_for_middle_nodes()
        # self.__build_graphs()  # build a graph network for nerve sets
        self.__find_continuous_paths(sources, targets)  # find all possible paths from sources to targets
        self.__extract_components()  # get all the coordinates and derivatives
        self.__generate_2d_descriptions()

    def __find_continuous_paths(self, sources, targets) -> None:
        """
        Builds a dictionary of every possible paths from a source to target for every nerve set.
        Assumptions is that sources and targets have only 1 input/output (i.e, nodes with degree of 1). Any node with
        more than 1 degree are ignored and treated as branching/connecting node.
        """
        path_id = 1
        for source in sources:
            for target in targets:
                nodes = nx.shortest_path(self.__path_network, source=source, target=target)
                if len(nodes) >= 2 and nodes not in self.__continuous_paths.values():
                    self.__continuous_paths[f'p_{path_id}'] = nodes
                    path_id += 1

    @staticmethod
    def __get_bezier_coefficients(segment):
    #======================================
        return ((p.x, p.y) for p in segment.points[0:4])

    def __extract_components(self) -> None:
        """
        Extracts and stores centreline components (i.e, coordinates & derivatives)
        in a dictionary for every nerve set. Each nerve set is a dict with keys
        corresponding to the keys in self.__continuous_paths.
        """
        node_geometry = self.__path_network.nodes(data='geometry')
        for path_id, path_nodes in self.__continuous_paths.items():
            for n1, n2 in pairwise(path_nodes):
                centreline = self.__get_centreline(n1, n2)
                self.__node_coordinates[path_id].append(node_geometry[n1].centroid.coords[0])  # assign node 1
                if centreline is None:
                    x2 = node_geometry[n2].centroid.x
                    y2 = node_geometry[n2].centroid.y
                    du = [0., 0.]
                    if len(self.__node_derivatives[path_id]) < 1:  # use the mean derivatives
                        self.__node_derivatives[path_id].append((du[0] * 0.001, du[1] * 0.001))  # assign derivative 1
                    self.__node_derivatives[path_id].append((du[0] * 0.001, du[1] * 0.001))  # assign derivative 2
                else:
                    for n, segment in enumerate(centreline.asSegments()):
                        b0, b1, b2, b3 = self.__get_bezier_coefficients(segment)
                        if n > 0:
                            self.__node_coordinates[path_id].append(b0)
                        du = mult(sub(b1, b0), 3)
                        if len(self.__node_derivatives[path_id]) > 1:  # use the mean derivatives
                            previous = self.__node_derivatives[path_id].pop()
                            du = mult(add(previous, du), 0.5)
                        self.__node_derivatives[path_id].append(du)  # assign derivative 1
                        du2 = mult(sub(b3, b2), 3)
                        self.__node_derivatives[path_id].append(du2)  # assign derivative 2
            self.__node_coordinates[path_id].append(node_geometry[path_nodes[-1]].centroid.coords[0])  # assign last coordinate

    def __get_centreline(self, n1: str, n2: str) -> BezierPath:
    #=========================================================
        if (n1, n2) in self.__path_network.edges:
            edge = self.__path_network.edges[n1, n2]
            bezier_path = edge.get('geometry')
            if bezier_path is not None:
                if n1 == edge.get('start-node'):
                    return bezier_path
                else:
                    segments = [bz.reversed() for bz in bezier_path.asSegments()]
                    segments.reverse()
                    return BezierPath.fromSegments(segments)
        return None

    def __generate_2d_descriptions(self) -> None:
    #============================================
        for path_id, path_nodes in self.__continuous_paths.items():
            number_of_nodes = len(path_nodes)
            node_coordinates = self.__node_coordinates[path_id]
            node_derivatives = self.__node_derivatives[path_id]

            assert len(node_coordinates) == len(node_derivatives), \
                "routing.routes: Number of nodes & derivatives do not match."

            self.__node_coordinates[path_id], self.__node_derivatives[path_id], _, _, _ = sample(node_coordinates,
                                                                                                 node_derivatives,
                                                                                                 number_of_nodes*7)

            self.__node_derivatives[path_id] = smooth_derivative(self.__node_coordinates[path_id],
                                                                 self.__node_derivatives[path_id],
                                                                 fix_all_directions=False,
                                                                 fix_start_derivative=False,
                                                                 fix_end_derivative=False,
                                                                 fix_start_direction=False,
                                                                 fix_end_direction=False)
            number_of_nodes = len(self.__node_coordinates[path_id])
            d1 = []
            d2 = []
            node_coords = []
            for node_index in range(number_of_nodes):
                x, y = self.__node_coordinates[path_id][node_index]
                dx, dy = self.__node_derivatives[path_id][node_index]
                if dx == 0 or dy == 0:
                    normal_left = [10, 100]
                    normal_right = [10, 10]
                else:
                    normal_left = mult(normalize([dy, -dx]), 10)
                    normal_right = mult(normalize([-dy, dx]), 10)
                # TODO: find a way to properly adjust the normals so that the 2D nodes are created appropriately.
                # normal_left = mult(normalize([dy, -dx]),
                #                    self.__estimate_width(nerve, path_id, node_index) * 0.5)
                # normal_right = mult(normalize([-dy, dx]),
                #                     self.__estimate_width(nerve, path_id, node_index) * 0.5)
                new_node1 = [x + normal_left[0], y + normal_left[1]]
                node_coords.append(new_node1)
                new_node2 = [x + normal_right[0], y + normal_right[1]]
                node_coords.append(new_node2)
                d1.append(set_magnitude(normal_left, magnitude(normal_left) * 1.))
                d1.append(set_magnitude(normal_right, magnitude(normal_right) * 1.))
                d2.append([dx, dy])
                d2.append([dx, dy])

            scaffold_settings = {
                'id': path_id,
                'node coordinates': node_coords,
                'node derivatives 1': d1,
                'node derivatives 2': d2,
                'number of elements': number_of_nodes - 1
            }
            scaffold = Scaffold2dPath(scaffold_settings)
            self.__continuous_region_scaffolds[path_id] = scaffold

    # See TODO above...
    # def __estimate_width(self, nerve: str, path_id: str, node_id: int) -> float:
    #    shape = self.__continuous_paths[nerve][path_id][node_id]
    #    shape_object = self.__node_geometry[shape]
    #    scale_x = get_geo_coordinates(shape_object.centroid.x, None)[0] / shape_object.centroid.x
    #    scale_y = get_geo_coordinates(None, shape_object.centroid.y)[1] / shape_object.centroid.y
    #    shape_rough_width = shape_object.length * ((scale_x + scale_y) / 2)
    #    return shape_rough_width


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

from collections import defaultdict

#===============================================================================

from beziers.path import BezierPath
import networkx as nx
import numpy as np

#===============================================================================

from mapmaker.utils import log
from mapmaker.routing.utils.pair_iteration import pairwise
from mapmaker.routing.utils.maths import magnitude
from mapmaker.routing.utils.maths import mult
from mapmaker.routing.utils.maths import normalize
from mapmaker.routing.utils.maths import set_magnitude
from mapmaker.routing.utils.maths import sub
from mapmaker.routing.utils.maths import add
from mapmaker.routing.utils.interpolation import smooth_cubic_hermite_derivatives_line
from mapmaker.routing.utils.interpolation import sample_cubic_hermite_curves
from mapmaker.routing.scaffold_2d import Scaffold2dPath

#===============================================================================

# See https://pomax.github.io/bezierinfo/#catmullconv

Bezier_to_Hermite = np.array([[ 1,  0,  0,  0],
                              [-3,  3,  0,  0],
                              [ 0,  0, -3,  3],
                              [ 0,  0,  0,  1]])

#===============================================================================

class ControlPoint(object):
    def __init__(self, position: np.array, derivative: np.array):
        self.__position = position
        self.__derivative = derivative

    def __str__(self):
        return(f'CP: ({self.__position}, {self.__derivative})')

    @property
    def position(self):
        return self.__position

    @property
    def derivative(self):
        return self.__derivative

    def set_position(self, position):
        self.__position = np.array(position)

    def smooth_slope(self, derivative: np.array) -> None:
        self.__derivative = 0.5*(self.__derivative + derivative)

#===============================================================================

class ControlPointList(list):

    def append(self, bezier):
        hermite = Bezier_to_Hermite@[[p.x, p.y] for p in bezier.points]
        if len(self) == 0:
            super().append(ControlPoint(hermite[0], hermite[1]))
        else:
            self[-1].smooth_slope(hermite[1])
        super().append(ControlPoint(hermite[3], hermite[2]))

#===============================================================================

class PathSegment(object):
    def __init__(self, start_region, connecting_path, end_region):
        self.__start_region = start_region
        self.__start_point = start_region.centroid.coords[0]
        self.__end_region = end_region
        self.__end_point = end_region.centroid.coords[0]
        self.__control_points = ControlPointList()
        if connecting_path is None:
            pass
        else:
            bezier_segments = connecting_path.asSegments()
            for bezier in bezier_segments:
                self.__control_points.append(bezier)

    @property
    def start_point(self):
        return self.__start_point

    @property
    def end_point(self):
        return self.__end_point

    @property
    def control_points(self):
        return self.__control_points

    def join(self, next_segment):
        # Adjust position and slope where next_segment joins
        last_control = self.__control_points[-1]
        last_control.set_position(next_segment.start_point)
        last_control.smooth_slope(next_segment.control_points[0].derivative)

#===============================================================================

class Sheath(object):
    def __init__(self, path_network: nx.Graph, path_id: str):
        self.__path_network = path_network
        self.__id = path_id
        self.__edges = None
        self.__node_geometry = None
        self.__control_points = defaultdict(list)
        self.__graphs = {}
        self.__continuous_paths = {}
        self.__scaffold_settings = {}
        self.__continuous_region_scaffolds = {}

    def settings(self) -> dict:
    #==========================
        path_ids = list(self.__continuous_paths)
        scaffolds = [self.__continuous_region_scaffolds[i] for i in path_ids]
        coordinates = [[c.position.tolist() for c in self.__control_points[i]] for i in path_ids]
        derivatives = [[c.derivative.tolist() for c in self.__control_points[i]] for i in path_ids]
        settings = {'scaffolds': scaffolds,
                    'path_ids': path_ids,
                    'derivatives': derivatives,
                    'coordinates': coordinates}
        return settings

    def build(self, sources, targets) -> None:
    #=========================================
        log('Generating pathway scaffold layout...')
        # self.__check_for_middle_nodes()
        # self.__build_graphs()  # build a graph network for nerve sets
        self.__find_continuous_paths(sources, targets)  # find all possible paths from sources to targets
        self.__extract_components()  # get all the coordinates and derivatives
        self.__generate_2d_descriptions()

    def __find_continuous_paths(self, sources, targets) -> None:
    #===========================================================
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

    def __extract_components(self) -> None:
    #======================================
        """
        Extracts and stores centreline components (i.e, coordinates & derivatives)
        in a dictionary for every nerve set. Each nerve set is a dict with keys
        corresponding to the keys in self.__continuous_paths.
        """
        node_geometry = self.__path_network.nodes(data='geometry')
        for path_id, path_nodes in self.__continuous_paths.items():
            # First derive the segments that connect the path's nodes
            path_segments = []
            for node_1, node_2 in pairwise(path_nodes):
                centreline = self.__get_centreline(node_1, node_2)
                segment = PathSegment(node_geometry[node_1], centreline, node_geometry[node_2])
                if len(path_segments) > 0:
                    path_segments[-1].join(segment)
                path_segments.append(segment)
            # And use them to set the control points for the path's centreline region
            for segment in path_segments:
                control_points = segment.control_points
                if len(self.__control_points[path_id]) == 0:
                    self.__control_points[path_id].append(control_points[0])
                self.__control_points[path_id].extend(control_points[1:])
            # The region starts and ends at the respective node centroids
            self.__control_points[path_id][0].set_position(path_segments[0].start_point)
            self.__control_points[path_id][-1].set_position(path_segments[-1].end_point)

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
        for path_id in self.__continuous_paths.keys():

            '''  Why?? Curves look nicer without this...
            self.__node_coordinates[path_id], node_derivatives, _, _, _ = sample_cubic_hermite_curves(self.__node_coordinates[path_id],
                                                                                                      self.__node_derivatives[path_id],
                                                                                                      number_of_nodes*7)  ## Why 7 ??????????
            self.__node_derivatives[path_id] = smooth_cubic_hermite_derivatives_line(self.__node_coordinates[path_id],
                                                                                     node_derivatives,
                                                                                     fix_all_directions=False,
                                                                                     fix_start_derivative=False,
                                                                                     fix_end_derivative=False,
                                                                                     fix_start_direction=False,
                                                                                     fix_end_direction=False)
            number_of_nodes = len(self.__node_coordinates[path_id])
            '''

            d1 = []
            d2 = []
            node_coords = []
            for control_point in self.__control_points[path_id]:
                x, y = control_point.position.tolist()
                dx, dy = control_point.derivative.tolist()
                if dx == 0 or dy == 0:
                    normal_left = [10, 10]
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
                'number of elements': len(self.__control_points[path_id]) - 1
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

#===============================================================================

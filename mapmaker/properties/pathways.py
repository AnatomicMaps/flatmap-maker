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

from pyparsing import delimitedList, Group, ParseResults, Suppress

#===============================================================================

from mapmaker.flatmap.layers import FeatureLayer
from mapmaker.pathrouter import PathRouter
from mapmaker.sources.markup import ID_TEXT
from mapmaker.utils import log, FilePath

#===============================================================================

NERVES = delimitedList(ID_TEXT)

LINE_ID = ID_TEXT
PATH_LINES = delimitedList(LINE_ID)

NODE_ID = ID_TEXT
ROUTE_NODE_GROUP = NODE_ID  | Group(Suppress('(') +  delimitedList(NODE_ID) + Suppress(')'))
ROUTE_NODES = delimitedList(ROUTE_NODE_GROUP)

#===============================================================================

def parse_path_lines(line_ids):
    try:
        if isinstance(line_ids, str):
            path_lines = PATH_LINES.parseString(line_ids, parseAll=True)
        else:
            path_lines = [LINE_ID.parseString(line_id)[0] for line_id in line_ids]
    except ParseException:
        raise ValueError('Syntax error in path lines list: {}'.format(line_ids))
    return path_lines

def parse_route_nodes(node_ids):
    try:
        if isinstance(node_ids, str):
            route_nodes = ROUTE_NODES.parseString(node_ids, parseAll=True)
        else:
            route_nodes = []
            if isinstance(node_ids[0], str):
                route_nodes.append(NODE_ID.parseString(node_ids[0]))
            else:
                route_nodes.append([NODE_ID.parseString(id)[0] for id in node_ids[0]])
            for id in node_ids[1:-1]:
                route_nodes.append(NODE_ID.parseString(id)[0])
            if isinstance(node_ids[-1], str):
                route_nodes.append(NODE_ID.parseString(node_ids[-1]))
            else:
                route_nodes.append([NODE_ID.parseString(id)[0] for id in node_ids[-1]])
    except ParseException:
        raise ValueError('Syntax error in route node list: {}'.format(node_ids))
    return list(route_nodes)

def parse_nerves(node_ids):
    try:
        nerves = NERVES.parseString(node_ids, parseAll=True)
    except ParseException:
        raise ValueError('Syntax error in nerve list: {}'.format(node_ids))
    return nerves

#===============================================================================

class FeatureIdMap(object):
    def __init__(self, id_map, class_map):
        self.__id_map = id_map
        self.__class_map = class_map

    def map(self, id):
        feature = self.__id_map.get(id)
        if feature is None:
            return [feature.feature_id for feature in self.__class_map.get(id, [])]
        return [feature.feature_id]

    def map_list(self, ids):
        feature_ids = []
        for id in ids:
            feature_id = self.map(id)
            if feature_id is not None:
                feature_ids.extend(feature_id)
        return feature_ids

#===============================================================================

class NodePaths(object):
    def __init__(self, feature_map):
        self.__feature_map = feature_map
        self.__paths = defaultdict(list)     # node_id: [ path_ids ]

    @property
    def as_dict(self):
        return self.__paths

    def __add_paths(self, path_id, nodes):
        for id in nodes:
            for node_id in self.__feature_map.map(id):
                self.__paths[node_id].append(path_id)

    def add_route(self, path_id, route):
        self.__add_paths(path_id, route.start_nodes)
        self.__add_paths(path_id, route.through_nodes)
        self.__add_paths(path_id, route.end_nodes)

#===============================================================================

class ResolvedPathways(object):
    def __init__(self, id_map, class_map):
        self.__feature_map = FeatureIdMap(id_map, class_map)
        self.__path_lines = defaultdict(list)
        self.__path_nerves = defaultdict(list)
        self.__node_paths = NodePaths(self.__feature_map)
        self.__type_paths = defaultdict(list)

    @property
    def node_paths(self):
        return self.__node_paths

    @property
    def path_lines(self):
        return self.__path_lines

    @property
    def path_nerves(self):
        return self.__path_nerves

    @property
    def type_paths(self):
        return self.__type_paths

    def add_pathway(self, path_id, lines, nerves, route):
        self.__path_lines[path_id].extend(self.__feature_map.map_list(lines))
        self.__path_nerves[path_id].extend(self.__feature_map.map_list(nerves))
        self.__node_paths.add_route(path_id, route)

    def add_path_type(self, path_id, path_type):
        self.__type_paths[path_type].append(path_id)

#===============================================================================

class Route(object):
    def __init__(self, model_id, path_id, route):
        self.__model_id = model_id
        self.__path_id = path_id
        routing = parse_route_nodes(route)
        if len(routing) < 2:
            raise ValueError('Route definition is too short for path {}'.format(path_id))
        self.__start_nodes = Pathways.make_list(routing[0])
        self.__through_nodes = []
        for node in routing[1:-1]:
            self.__through_nodes += Pathways.make_list(node)
        self.__end_nodes = Pathways.make_list(routing[-1])

    @property
    def start_nodes(self):
        return self.__start_nodes

    @property
    def through_nodes(self):
        return self.__through_nodes

    @property
    def end_nodes(self):
        return self.__end_nodes

#===============================================================================

class Pathways(object):
    def __init__(self, flatmap, paths_list):
        self.__flatmap = flatmap
        self.__layer_paths = set()
        self.__lines_by_path_id = defaultdict(list)
        self.__nerves_by_path_id = {}
        self.__paths_by_line_id = defaultdict(list)
        self.__paths_by_nerve_id = defaultdict(list)
        self.__resolved_pathways = None
        self.__routes_by_path_id = {}
        self.__types_by_path_id = {}
        self.__nerve_tracks = []
        self.__path_models = {}

    @staticmethod
    def make_list(lst):
        return (lst if isinstance(lst, list)
           else list(lst) if isinstance(lst, ParseResults)
           else [ lst ])

    @property
    def resolved_pathways(self):
        return {
            'path-lines': self.__resolved_pathways.path_lines,
            'path-nerves': self.__resolved_pathways.path_nerves,
            'node-paths': self.__resolved_pathways.node_paths.as_dict,
            'type-paths': self.__resolved_pathways.type_paths
            }

    def add_path(self, id):
        properties = {}
        if id in self.__paths_by_line_id:
            path_id = self.__paths_by_line_id[id][0]
            if path_id in self.__types_by_path_id:
                properties['kind'] = self.__types_by_path_id[path_id]
                properties['type'] = 'line-dash' if properties['kind'].endswith('-post') else 'line'
            else:
                properties['type'] = 'line'
            properties['tile-layer'] = 'pathways'
            self.__layer_paths.add(path_id)
        elif id in self.__paths_by_nerve_id:
            path_id = self.__paths_by_nerve_id[id][0]
            properties['tile-layer'] = 'pathways'
            properties['type'] = 'nerve'
            self.__layer_paths.add(path_id)
        return properties

    def add_nerve_tracks(self, nerve_tracks):
    #========================================
        self.__nerve_tracks.extend(nerve_tracks)

    def extend_pathways(self, model_id, paths_list, layout=False):
    #=============================================================
        lines_by_path_id = defaultdict(list)
        nerves_by_path_id = {}
        for path in paths_list:
            path_id = path['id']
            if 'path' in path:
                for line_group in parse_path_lines(path['path']):
                    lines_by_path_id[path_id] += Pathways.make_list(line_group)
                if 'route' not in path:
                    raise ValueError("Path '{}' doesn't have a route".format(path_id))
                self.__routes_by_path_id[path_id] = Route(model_id, path_id, path['route'])
                if 'nerves' in path:
                    nerves_by_path_id[path_id] = list(parse_nerves(path['nerves']))
                if 'type' in path:
                    self.__types_by_path_id[path_id] = path['type']
        self.__lines_by_path_id.update(lines_by_path_id)
        for path_id, lines in lines_by_path_id.items():
            for line_id in lines:
                self.__paths_by_line_id[line_id].append(path_id)
        self.__nerves_by_path_id.update(nerves_by_path_id)
        for path_id, nerves in nerves_by_path_id.items():
            for nerve_id in nerves:
                self.__paths_by_nerve_id[nerve_id].append(path_id)
        if layout:
            self.__path_models[model_id] = paths_list

    def __route_paths(self, id_map, class_map):
    #==========================================
        def get_point(node_id):
            if node_id in id_map:
                return id_map[node_id].geometry.centroid.coords[0]
            elif node_id in class_map:
                features = class_map[node_id]
                if len(features) == 1:
                    return features[0].geometry.centroid.coords[0]
            log.warn("Cannot find node '{}' for route".format(node_id))

        log('Routing paths...')
        router = PathRouter([track.properties['bezier-segments']
                    for track in self.__nerve_tracks])
        for model_id, paths in self.__path_models.items():
            for path in paths:
                if ( path['id'] != 'path_1' and #'path' not in path and
                    'route' in path):
                    route = Route(model_id, path['id'], path['route'])
                    points = ([ [ get_point(node) for node in route.start_nodes ] ]
                            + [ get_point(node) for node in route.through_nodes ]
                            + [ [ get_point(node) for node in route.end_nodes ] ])
                    router.add_route(model_id, path['id'], path.get('type', ''), points)

        layer = FeatureLayer('{}_routes'.format(self.__flatmap.id), base_layer=True)
        self.__flatmap.add_layer(layer)
        for model_id in self.__path_models.keys():
            for route in router.get_routes(model_id):
                if route.geometry is not None:
                    ## Properties need to come via `pathways` module...
                    layer.add_feature(self.__flatmap.new_feature(route.geometry,
                        { 'tile-layer': 'pathways',
                          'kind': route.kind,
                          'type': 'line-dash' if route.kind.endswith('-post') else 'line'
                        }))


    def resolve_pathways(self, id_map, class_map):
    #=============================================
        if self.__resolved_pathways is not None:
            return
        self.__route_paths(id_map, class_map)
        self.__resolved_pathways = ResolvedPathways(id_map, class_map)
        errors = False
        for path_id in self.__layer_paths:
            try:
                self.__resolved_pathways.add_pathway(path_id,
                                                     self.__lines_by_path_id.get(path_id, []),
                                                     self.__nerves_by_path_id.get(path_id, []),
                                                     self.__routes_by_path_id.get(path_id)
                                                    )
                self.__resolved_pathways.add_path_type(path_id, self.__types_by_path_id.get(path_id))
            except ValueError as err:
                print('Path {}: {}'.format(path_id, str(err)))
                errors = True
        if errors:
            raise ValueError('Errors in mapping paths and routes')

#===============================================================================

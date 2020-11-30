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
import json

#===============================================================================

from pyparsing import delimitedList, Group, ParseResults, Suppress

#===============================================================================

from mapmaker.sources.markup import ID_TEXT

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
    return route_nodes

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
        feature_id = self.__id_map.get(id)
        if feature_id is None:
            return self.__class_map.get(id, [])
        return [feature_id]

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
        self.__start_paths = defaultdict(list)     # node_id: [ path_ids ]
        self.__through_paths = defaultdict(list)   # node_id: [ path_ids ]
        self.__end_paths = defaultdict(list)       # node_id: [ path_ids ]

    @property
    def as_dict(self):
        return {
            'start-paths': self.__start_paths,
            'through-paths': self.__through_paths,
            'end-paths': self.__end_paths
        }

    def __add_paths(self, path_id, nodes, paths_dict):
        for id in nodes:
            for node_id in self.__feature_map.map(id):
                paths_dict[node_id].append(path_id)

    def add_route(self, path_id, route_nodes):
        self.__add_paths(path_id, route_nodes['start-nodes'], self.__start_paths)
        self.__add_paths(path_id, route_nodes['through-nodes'], self.__through_paths)
        self.__add_paths(path_id, route_nodes['end-nodes'], self.__end_paths)

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

    def add_pathway(self, path_id, lines, nerves, route_nodes):
        self.__path_lines[path_id].extend(self.__feature_map.map_list(lines))
        self.__path_nerves[path_id].extend(self.__feature_map.map_list(nerves))
        self.__node_paths.add_route(path_id, route_nodes)

    def add_path_type(self, path_id, path_type):
        self.__type_paths[path_type].append(path_id)

#===============================================================================

class Pathways(object):
    def __init__(self, paths_list):
        self.__lines_by_path_id = {}
        self.__routes_by_path_id = {}
        self.__nerves_by_path_id = {}
        self.__types_by_path_id = {}
        self.__layer_paths = set()
        self.__resolved_pathways = None
        for path in paths_list:
            path_id = path['id']
            self.__lines_by_path_id[path_id] = []
            for line_group in parse_path_lines(path['path']):
                self.__lines_by_path_id[path_id] += Pathways.__make_list(line_group)
            if 'route' in path:
                routing = list(parse_route_nodes(path['route']))
                if len(routing) < 2:
                    raise ValueError('Route definition is too short for path {}'.format(path_id))
                through_nodes = []
                for node in routing[1:-1]:
                    through_nodes += Pathways.__make_list(node)
                self.__routes_by_path_id[path_id] = {
                    'start-nodes': Pathways.__make_list(routing[0]),
                    'through-nodes': through_nodes,
                    'end-nodes': Pathways.__make_list(routing[-1]),
                }
            if 'nerves' in path:
                self.__nerves_by_path_id[path_id] = list(parse_nerves(path['nerves']))
            if 'type' in path:
                self.__types_by_path_id[path_id] = path['type']

        self.__paths_by_line_id = defaultdict(list)
        for path_id, lines in self.__lines_by_path_id.items():
            for line_id in lines:
                self.__paths_by_line_id[line_id].append(path_id)

        self.__paths_by_nerve_id = defaultdict(list)
        for path_id, nerves in self.__nerves_by_path_id.items():
            for nerve_id in nerves:
                self.__paths_by_nerve_id[nerve_id].append(path_id)

    @staticmethod
    def __make_list(lst):
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

    def resolve_pathways(self, id_map, class_map):
        if self.__resolved_pathways is not None:
            return
        self.__resolved_pathways = ResolvedPathways(id_map, class_map)
        errors = False
        for path_id in self.__layer_paths:
            try:
                self.__resolved_pathways.add_pathway(path_id,
                                                     self.__lines_by_path_id.get(path_id, []),
                                                     self.__nerves_by_path_id.get(path_id, []),
                                                     self.__routes_by_path_id.get(path_id, {
                                                        'start-nodes': [],
                                                        'through-nodes': [],
                                                        'end-nodes': [],
                                                     })
                                                    )
                self.__resolved_pathways.add_path_type(path_id, self.__types_by_path_id.get(path_id))
            except ValueError as err:
                print('Path {}: {}'.format(path_id, str(err)))
                errors = True
        if errors:
            raise ValueError('Errors in mapping paths and routes')

#===============================================================================

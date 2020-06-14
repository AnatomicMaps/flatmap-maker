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
import pyparsing

#===============================================================================

try:
    from parser import Parser
except ImportError:
    from mapmaker.parser import Parser

#===============================================================================

class FeatureIdMap(object):
    def __init__(self, id_map, class_map, class_count):
        self.__id_map = id_map
        self.__class_map = class_map
        self.__class_count = class_count

    def map(self, id):
        feature_id = self.__id_map.get(id)
        if feature_id is None:
            feature_id = self.__class_map.get(id)
            if feature_id is not None and self.__class_count[id] > 1:
                raise ValueError('Route has node with duplicated class: {}'.format(id))
        return feature_id

    def map_list(self, ids):
        feature_ids = []
        for id in ids:
            feature_id = self.map(id)
            if feature_id is not None:
                feature_ids.append(feature_id)
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
            node_id = self.__feature_map.map(id)
            if node_id is not None:
                paths_dict[node_id].append(path_id)

    def add_route(self, path_id, route_nodes):
        self.__add_paths(path_id, route_nodes['start-nodes'], self.__start_paths)
        self.__add_paths(path_id, route_nodes['through-nodes'], self.__through_paths)
        self.__add_paths(path_id, route_nodes['end-nodes'], self.__end_paths)

    def update(self, other):
        self.__start_paths.update(other.__start_paths)
        self.__through_paths.update(other.__through_paths)
        self.__end_paths.update(other.__end_paths)

#===============================================================================

class ResolvedPathways(object):
    def __init__(self, id_map, class_map, class_count):
        self.__feature_map = FeatureIdMap(id_map, class_map, class_count)
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
            for line_group in Parser.path_lines(path['path']):
                self.__lines_by_path_id[path_id] += Pathways.__make_list(line_group)
            if 'route' in path:
                routing = list(Parser.route_nodes(path['route']))
                if len(routing) < 2:
                    raise ValueError('Route definition is too short for path {}'.format(path_id))
                through_nodes = []
                for node in routing[1:-2]:
                    through_nodes += Pathways.__make_list(node)
                self.__routes_by_path_id[path_id] = {
                    'start-nodes': Pathways.__make_list(routing[0]),
                    'through-nodes': through_nodes,
                    'end-nodes': Pathways.__make_list(routing[-1]),
                }
            if 'nerves' in path:
                self.__nerves_by_path_id[path_id] = list(Parser.nerves(path['nerves']))
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
        return list(lst) if isinstance(lst, pyparsing.ParseResults) else [ lst ]

    @property
    def resolved_pathways(self):
        return self.__resolved_pathways

    def properties(self, id):
        result = {}
        if id in self.__paths_by_line_id:
            path_id = self.__paths_by_line_id[id][0]
            if path_id in self.__types_by_path_id:
                result['kind'] = self.__types_by_path_id[path_id]
                result['type'] = 'line-dash' if result['kind'].endswith('-post') else 'line'
            else:
                result['type'] = 'line'
            result['path-id'] = path_id
            result['tile-layer'] = 'pathways'
            self.__layer_paths.add(path_id)
        elif id in self.__paths_by_nerve_id:
            path_id = self.__paths_by_nerve_id[id][0]
            result['path-id'] = path_id
            result['tile-layer'] = 'pathways'
            result['type'] = 'nerve'
            self.__layer_paths.add(path_id)
        return result

    def set_feature_ids(self, id_map, class_map, class_count):
        if self.__resolved_pathways is not None:
            return
        self.__resolved_pathways = ResolvedPathways(id_map, class_map, class_count)
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

def pathways_to_json(pathways_list):
    path_lines = {}
    path_nerves = {}
    node_paths = NodePaths(None)
    type_paths = {}
    for resolved_pathways in pathways_list:
        path_lines.update(resolved_pathways.path_lines)
        path_nerves.update(resolved_pathways.path_nerves)
        node_paths.update(resolved_pathways.node_paths)
        type_paths.update(resolved_pathways.type_paths)
    return json.dumps({
        'path-lines': path_lines,
        'path-nerves': path_nerves,
        'node-paths': node_paths.as_dict,
        'type-paths': type_paths
        })

#===============================================================================

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

import json

#===============================================================================

class NodePaths(object):
    def __init__(self):
        self.__start_paths = {}     # node_id: [ path_ids ]
        self.__through_paths = {}   # node_id: [ path_ids ]
        self.__end_paths = {}       # node_id: [ path_ids ]

    @property
    def as_dict(self):
        return {
            'start-paths': self.__start_paths,
            'through-paths': self.__through_paths,
            'end-paths': self.__end_paths
        }

    def add_route(self, path_id, route_nodes):
        for node_id in route_nodes['start-nodes']:
            if node_id not in self.__start_paths:
                self.__start_paths[node_id] = [ path_id ]
            else:
                self.__start_paths[node_id].append(path_id)
        for node_id in route_nodes['through-nodes']:
            if node_id not in self.__through_paths:
                self.__through_paths[node_id] = [ path_id ]
            else:
                self.__through_paths[node_id].append(path_id)
        for node_id in route_nodes['end-nodes']:
            if node_id not in self.__end_paths:
                self.__end_paths[node_id] = [ path_id ]
            else:
                self.__end_paths[node_id].append(path_id)

    def map_ids(self, feature_map):
        result = NodePaths()
        for id, paths in self.__start_paths.items():
            node_id = feature_map.map(id)
            if node_id is not None:
                node_paths = feature_map.map_list(paths)
                if node_id in result.__start_paths:
                    result.__start_paths[node_id].extend(node_paths)
                else:
                    result.__start_paths[node_id] = node_paths
        for id, paths in self.__through_paths.items():
            node_id = feature_map.map(id)
            if node_id is not None:
                node_paths = feature_map.map_list(paths)
                if node_id in result.__through_paths:
                    result.__through_paths[node_id].extend(node_paths)
                else:
                    result.__through_paths[node_id] = node_paths
        for id, paths in self.__end_paths.items():
            node_id = feature_map.map(id)
            if node_id is not None:
                node_paths = feature_map.map_list(paths)
                if node_id in result.__end_paths:
                    result.__end_paths[node_id].extend(node_paths)
                else:
                    result.__end_paths[node_id] = node_paths
        return result

    def update(self, other):
        self.__start_paths.update(other.__start_paths)
        self.__through_paths.update(other.__through_paths)
        self.__end_paths.update(other.__end_paths)

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

class LayerPathways(object):
    def __init__(self):
        self.__path_lines = {}
        self.__node_paths = NodePaths()

    @property
    def node_paths(self):
        return self.__node_paths

    @property
    def path_lines(self):
        return self.__path_lines

    def add_pathway(self, id, path_lines, route_nodes):
        self.__path_lines[id] = path_lines
        self.__node_paths.add_route(id, route_nodes)

    def as_feature_ids(self, id_map, class_map, class_count):
        feature_map = FeatureIdMap(id_map, class_map, class_count)
        result = LayerPathways()
        for id, lines in self.__path_lines.items():
            path_id = feature_map.map(id)
            if path_id is not None:
                path_lines = feature_map.map_list(lines)
                if path_id in result.__path_lines:
                    result.__path_lines[path_id].extend(path_lines)
                else:
                    result.__path_lines[path_id] = path_lines
        result.__node_paths = self.__node_paths.map_ids(feature_map)
        return result

#===============================================================================

class MapPathways(object):
    def __init__(self):
        self.__path_lines = {}
        self.__node_paths = NodePaths()

    def add_layer(self, pathways):
        self.__path_lines.update(pathways.path_lines)
        self.__node_paths.update(pathways.node_paths)

    def json(self):
        return json.dumps({
            'path-lines': self.__path_lines,
            'node-paths': self.__node_paths.as_dict
            })

#===============================================================================

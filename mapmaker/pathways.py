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

    def map_ids(self, id_map):
        result = NodePaths()
        for id, paths in self.__start_paths.items():
            if id_map.get(id) is not None:
                result.__start_paths[id_map[id]] = [
                    id_map[path] for path in paths if id_map.get(path) is not None]
        for id, paths in self.__through_paths.items():
            if id_map.get(id) is not None:
                result.__through_paths[id_map[id]] = [
                    id_map[path] for path in paths if id_map.get(path) is not None]
        for id, paths in self.__end_paths.items():
            if id_map.get(id) is not None:
                result.__end_paths[id_map[id]] = [
                    id_map[path] for path in paths if id_map.get(path) is not None]
        return result

    def update(self, other):
        self.__start_paths.update(other.__start_paths)
        self.__through_paths.update(other.__through_paths)
        self.__end_paths.update(other.__end_paths)

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

    def map_ids(self, id_map):
        result = LayerPathways()
        for id, lines in self.__path_lines.items():
            if id_map.get(id) is not None:
                result.__path_lines[id_map[id]] = [
                    id_map[line] for line in lines if id_map.get(line) is not None]
        result.__node_paths = self.__node_paths.map_ids(id_map)
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
            'node_paths': self.__node_paths.as_dict
            })

#===============================================================================

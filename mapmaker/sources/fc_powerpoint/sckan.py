#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2023  David Brooks
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
from typing import Optional

from pprint import pprint

#===============================================================================

import mapmaker.knowledgebase as knowledgebase

#===============================================================================

class SckanNodeSet:
    def __init__(self):
        self.__node_dict: dict[str, set[tuple[str, ...]]] = defaultdict(set)
        ## WIP self.__paths_by_node = {}   ## WIP to have all nodes of all paths in one node set

    def add_path(self, path_id: str, sckan_nodes: set[tuple[str, tuple[str, ...]]]):
    #===============================================================================
        for sckan_node in sckan_nodes:
            self.__add_node(path_id, sckan_node)

    def __add_node(self, path_id: str, sckan_node: tuple[str, tuple[str, ...]]):
    #===========================================================================
        node_list = [sckan_node[0]]
        node_list.extend(sckan_node[1])
        while len(node_list):
            self.__node_dict[node_list[0]].add(tuple(node_list[1:]))
            node_list.pop(0)

    def has_connector(self, ftu: str, organ: Optional[str]=None) -> bool:
    #===========================================================
        if (node_layers := self.__node_dict.get(ftu)) is not None:
            if organ is None:
                return True
            else:
                for layers in node_layers:
                    if organ in layers:
                        return True
        return organ is not None and self.__node_dict.get(organ) is not None

#===============================================================================

class SckanNeuronPopulations:
    def __init__(self):
        ## WIP self.__sckan_nodes = SckanNodeSet()  ## WIP to have all nodes of all paths in one node set
        self.__sckan_nodes_by_path: dict[str, SckanNodeSet] = {}  ## WIP to have all nodes of all paths in one node set
        self.__paths_by_id = {}
        connectivity_models = knowledgebase.connectivity_models()
        for model in connectivity_models:
            model_knowledege = knowledgebase.get_knowledge(model)
            for path in model_knowledege['paths']:
                path_knowledge = knowledgebase.get_knowledge(path['id'])
                self.__paths_by_id[path['id']] = path_knowledge
                nodes: set[tuple[str, tuple[str, ...]]] = set()
                for connection in path_knowledge['connectivity']:   ## Should really return this as neseted tuples...
                    for node in connection:
                        nodes.add((node[0], tuple(node[1])))
                ## WIP self.__sckan_nodes.add_path(path['id'], nodes)
                self.__sckan_nodes_by_path[path['id']] = SckanNodeSet()   ## WIP
                self.__sckan_nodes_by_path[path['id']].add_path(path['id'], nodes)  ## WIP

    def find_connection_paths(self, end_nodes: list[tuple[str, Optional[str]]]) -> list[str]:
    #========================================================================================
        path_ids = []
        for path_id, node_set in self.__sckan_nodes_by_path.items():
            if (node_set.has_connector(*end_nodes[0])
            and node_set.has_connector(*end_nodes[1])):
                path_ids.append(path_id)
        return path_ids

    def knowledge(self, path_id: str) -> Optional[dict]:
    #===================================================
        return self.__paths_by_id.get(path_id)

#===============================================================================

"""
{
 'id': 'https://apinatomy.org/uris/models/spleen',
 'paths': [
    {'id': 'ilxtr:neuron-type-splen-5', 'models': 'ilxtr:neuron-type-splen-5'},
    {'id': 'ilxtr:neuron-type-splen-4', 'models': 'ilxtr:neuron-type-splen-4'},
    {'id': 'ilxtr:neuron-type-splen-3', 'models': 'ilxtr:neuron-type-splen-3'},
    {'id': 'ilxtr:neuron-type-splen-1', 'models': 'ilxtr:neuron-type-splen-1'},
    {'id': 'ilxtr:neuron-type-splen-2', 'models': 'ilxtr:neuron-type-splen-2'}
  ],
 'references': [
    'PMID:32061636',
    'PMID:14565534',
    'PMID:33491187',
    'PMID:24411268',
    'splen:0'
  ],
 'label': 'https://apinatomy.org/uris/models/spleen'}



{
 'id': 'ilxtr:neuron-type-splen-1',
 'label': 'neuron type splen 1',
 'long-label': 'neuron type splen 1',
 'references': [],
 'axons': [
    ['ILX:0793082', []]
 ],
 'dendrites': [
    ['UBERON:0006456', []],
    ['UBERON:0006453', []],
    ['UBERON:0006455', []],
    ['UBERON:0006454', []]
 ],
 'connectivity': [
    [ ['UBERON:0018680', []], ['ILX:0793082', []] ],
    [ ['UBERON:0006456', []], ['UBERON:0018680', []] ],
    [ ['UBERON:0006453', []], ['UBERON:0018680', []] ],
    [ ['UBERON:0006455', []], ['UBERON:0018680', []] ],
    [ ['UBERON:0006454', []], ['UBERON:0018680', []] ]
 ],
 'errors': [],
 'phenotypes': [
    'ilxtr:PreGanglionicPhenotype',
    'ilxtr:SympatheticPhenotype'
  ]
}
"""

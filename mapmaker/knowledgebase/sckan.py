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
import enum
from typing import Optional

#===============================================================================

import networkx as nx

#===============================================================================

from mapmaker.utils import log

import mapmaker.knowledgebase as kb
from .annotator import AnnotatorDatabase

#===============================================================================

class PATH_TYPE(enum.IntFlag):
    UNKNOWN             = 0
    #
    CNS                 = 1
    ENTERIC             = 2
    EXCITORY            = 3
    INHIBITORY          = 4
    INTESTIONO_FUGAL    = 5
    INTRINSIC           = 6
    MOTOR               = 7
    PARASYMPATHETIC     = 8
    SENSORY             = 9
    SPINAL_ASCENDING    = 10
    SPINAL_DESCENDING   = 11
    SYMPATHETIC         = 12
    # These can be or'd with the above
    POST_GANGLIONIC     = 32
    PRE_GANGLIONIC      = 64
    # Mask out PRE/POST status
    MASK_PRE_POST       = 31
    MASK_PATH_TYPE      = 96

    @staticmethod
    def __path_name(path_type):
        return {
            PATH_TYPE.UNKNOWN: 'unknown',
            PATH_TYPE.CNS: 'cns',
            PATH_TYPE.ENTERIC: 'enteric',
            PATH_TYPE.EXCITORY: 'excitatory',
            PATH_TYPE.INHIBITORY: 'inhibitory',
            PATH_TYPE.INTESTIONO_FUGAL: 'intestine',
            PATH_TYPE.INTRINSIC: 'intracardiac',
            PATH_TYPE.MOTOR: 'somatic',     ## Rename to 'motor' but will need viewer update...
            PATH_TYPE.PARASYMPATHETIC: 'para',
            PATH_TYPE.SENSORY: 'sensory',
            PATH_TYPE.SPINAL_ASCENDING: 'cns',
            PATH_TYPE.SPINAL_DESCENDING: 'cns',
            PATH_TYPE.SYMPATHETIC: 'symp',
            PATH_TYPE.POST_GANGLIONIC: 'post',
            PATH_TYPE.PRE_GANGLIONIC: 'pre'
        }[path_type]

    def __str__(self):
        if (pre_post := (self & PATH_TYPE.MASK_PATH_TYPE).value):
            return f'{self.__path_name(self & PATH_TYPE.MASK_PRE_POST)}-{self.__path_name(pre_post)}'
        else:
            return self.__path_name(self)

#===============================================================================

PATH_TYPE_BY_PHENOTYPE = {
    'ilxtr:MotorPhenotype':                             PATH_TYPE.MOTOR,
    'ilxtr:ParasympatheticPhenotype':                   PATH_TYPE.PARASYMPATHETIC,
    'ilxtr:SensoryPhenotype':                           PATH_TYPE.SENSORY,
    'ilxtr:SympatheticPhenotype':                       PATH_TYPE.SYMPATHETIC,
    'ilxtr:IntrinsicPhenotype':                         PATH_TYPE.INTRINSIC,
    'ilxtr:SpinalCordAscendingProjectionPhenotype':     PATH_TYPE.SPINAL_ASCENDING,
    'ilxtr:SpinalCordDescendingProjectionPhenotype':    PATH_TYPE.SPINAL_DESCENDING,
    'ilxtr:EntericPhenotype':                           PATH_TYPE.ENTERIC,
    'ilxtr:IntestinoFugalProjectionPhenotype':          PATH_TYPE.INTESTIONO_FUGAL,
    'ILX:0104003':                                      PATH_TYPE.EXCITORY,
    'ILX:0105486':                                      PATH_TYPE.INHIBITORY
}

PATH_ORDER_BY_PHENOTYPE = {
    'ilxtr:PostGanglionicPhenotype':    PATH_TYPE.POST_GANGLIONIC,
    'ilxtr:PreGanglionicPhenotype':     PATH_TYPE.PRE_GANGLIONIC,
}

def path_type_from_phenotypes(phenotypes) -> PATH_TYPE:
#======================================================
    path_type = PATH_TYPE.UNKNOWN
    for phenotype in phenotypes:
        if (path_type := PATH_TYPE_BY_PHENOTYPE.get(phenotype, PATH_TYPE.UNKNOWN)) != PATH_TYPE.UNKNOWN:
            break
    if path_type == PATH_TYPE.UNKNOWN:
        return path_type
    for phenotype in phenotypes:
        if (path_order := PATH_ORDER_BY_PHENOTYPE.get(phenotype)) is not None:
            return path_type | path_order
    return path_type

#===============================================================================

def connectivity_graph_from_knowledge(knowledge: dict) -> Optional[nx.Graph]:
    if 'connectivity' in knowledge:
        # Construct a graph of SciCrunch's connected pairs
        G = nx.Graph()
        phenotypes = knowledge.get('phenotypes', [])
        path_type = path_type_from_phenotypes(phenotypes)
        if path_type == PATH_TYPE.UNKNOWN:
            log.warning(f'SCKAN knowledge error: Phenotype {phenotypes} is unknown, defaulting to CNS')
            path_type = PATH_TYPE.CNS
        G.graph['path-type'] = path_type
        for node in knowledge.get('connectivity', []):
            node_0 = kb.AnatomicalNode(node[0])
            node_1 = kb.AnatomicalNode(node[1])
            G.add_edge(node_0, node_1)
        return G

#===============================================================================

class SckanNodeSet:
    def __init__(self, path_id, connectivity_graph):
        self.__id = path_id
        self.__node_dict: dict[str, set[tuple[str, ...]]] = defaultdict(set)
        # Normalise nodes and remove any duplicates
        nodes = {node.normalised() for node in connectivity_graph.nodes}
        # Build an index with successive terms of a node's tuple
        # identifying any following terms
        for node in nodes:
            node_list = list(node)
            while len(node_list):
                if len(node_list) > 1:
                    self.__node_dict[node_list[0]].add(tuple(node_list[1:]))
                else:
                    self.__node_dict[node_list[0]] = set()
                node_list.pop(0)

    def has_connector(self, ftu: str, organ: Optional[str]=None) -> bool:
    #====================================================================
        if (node_layers := self.__node_dict.get(ftu)) is not None:
            if organ is None or len(node_layers) == 0:
                return True
            else:
                for layers in node_layers:
                    if organ in layers:
                        return True
        return organ is not None and self.__node_dict.get(organ) is not None

#===============================================================================

class SckanNeuronPopulations:
    def __init__(self, flatmap_dir):
        self.__annotator_database = AnnotatorDatabase(flatmap_dir)
        self.__sckan_path_nodes_by_type: dict[PATH_TYPE, dict[str, SckanNodeSet]] = defaultdict(dict[str, SckanNodeSet])
        self.__paths_by_id = {}
        connectivity_models = kb.connectivity_models()
        for model in connectivity_models:
            model_knowledege = kb.get_knowledge(model)
            for path in model_knowledege['paths']:
                path_knowledge = kb.get_knowledge(path['id'])
                self.__paths_by_id[path['id']] = path_knowledge
        self.__unknown_connections = []
                G = connectivity_graph_from_knowledge(path_knowledge)
                if G:
                    path_type = G.graph['path-type']
                    self.__sckan_path_nodes_by_type[path_type][path['id']] = SckanNodeSet(path['id'], G)

    def lookup_connection(self, neuron_id: str,
                                end_nodes: list[tuple[str, Optional[str]]],
                                intermediates: list[tuple[str, Optional[str]]],
                                path_type: PATH_TYPE) -> list[str]:
    #==========================================================================
        path_ids = []
        for path_id, node_set in self.__sckan_path_nodes_by_type[path_type].items():
            if (node_set.has_connector(*end_nodes[0])
            and node_set.has_connector(*end_nodes[1])):
                path_ids.append(path_id)
        # Keep track of neuron paths we've found (or not found)
        if len(path_ids) == 0:
            evidence = {
                'id': neuron_id,
                'endNodes': tuple(sorted(end_nodes)),
                'type': str(path_type),
                'evidence': self.__annotator_database.get_derivation(neuron_id)
            }
            if len(intermediates):
                evidence['intermediates'] = intermediates
            self.__unknown_connections.append(evidence)
        return path_ids

    def unknown_connections_with_evidence(self):
    #===========================================
        return [data for data in self.__unknown_connections if data['evidence']]

    def knowledge(self, path_id: str) -> Optional[dict]:
    #===================================================
        return self.__paths_by_id.get(path_id)

    def path_label(self, path_id: str) -> Optional[str]:
    #===================================================
        return self.__paths_by_id.get(path_id, {}).get('label')

#===============================================================================

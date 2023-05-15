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

from mapmaker.settings import settings
from mapmaker.utils import log

import mapmaker.knowledgebase as kb
from .annotator import AnnotatorDatabase

#===============================================================================

class PATH_TYPE(enum.IntFlag):
    UNKNOWN             = 0
    #
    CNS                 = 1
    ENTERIC             = 2
    EXCITATORY          = 3
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

    def __name(self):
        return {
            PATH_TYPE.UNKNOWN: 'unknown',
            PATH_TYPE.CNS: 'central nervous system',
            PATH_TYPE.ENTERIC: 'enteric',
            PATH_TYPE.EXCITATORY: 'excitatory',
            PATH_TYPE.INHIBITORY: 'inhibitory',
            PATH_TYPE.INTESTIONO_FUGAL: 'intestinal',
            PATH_TYPE.INTRINSIC: 'intracardiac',
            PATH_TYPE.MOTOR: 'motor',
            PATH_TYPE.PARASYMPATHETIC: 'parasympathetic',
            PATH_TYPE.SENSORY: 'sensory',
            PATH_TYPE.SPINAL_ASCENDING: 'spinal ascending',
            PATH_TYPE.SPINAL_DESCENDING: 'spinal descending',
            PATH_TYPE.SYMPATHETIC: 'sympathetic',
            PATH_TYPE.POST_GANGLIONIC: 'post-ganglionic',
            PATH_TYPE.PRE_GANGLIONIC: 'pre-ganglionic'
        }[self]

    def __viewer_kind(self):
        return {
            PATH_TYPE.UNKNOWN: 'unknown',
            PATH_TYPE.CNS: 'cns',
            PATH_TYPE.ENTERIC: 'enteric',
            PATH_TYPE.EXCITATORY: 'excitatory',
            PATH_TYPE.INHIBITORY: 'inhibitory',
            PATH_TYPE.INTESTIONO_FUGAL: 'intestinal',
            PATH_TYPE.INTRINSIC: 'intracardiac',
            PATH_TYPE.MOTOR: 'somatic',     ## Rename to 'motor' but will need viewer update...
            PATH_TYPE.PARASYMPATHETIC: 'para',
            PATH_TYPE.SENSORY: 'sensory',
            PATH_TYPE.SPINAL_ASCENDING: 'cns',
            PATH_TYPE.SPINAL_DESCENDING: 'cns',
            PATH_TYPE.SYMPATHETIC: 'symp',
            PATH_TYPE.POST_GANGLIONIC: 'post',
            PATH_TYPE.PRE_GANGLIONIC: 'pre'
        }[self]

    @property
    def name(self):
        if pre_post := (self & PATH_TYPE.MASK_PATH_TYPE):
            return f'{pre_post.__name()} {(self & PATH_TYPE.MASK_PRE_POST).__name()}'
        else:
            return self.__name()

    @property
    def viewer_kind(self):
        if pre_post := (self & PATH_TYPE.MASK_PATH_TYPE):
            return f'{(self & PATH_TYPE.MASK_PRE_POST).__viewer_kind()}-{pre_post.__viewer_kind()}'
        else:
            return self.__viewer_kind()

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
    'ILX:0104003':                                      PATH_TYPE.EXCITATORY,
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

class SckanNeuronChecker:
    def __init__(self, flatmap):
        self.__sckan_path_nodes_by_type: defaultdict[PATH_TYPE, dict[str, SckanNodeSet]] = defaultdict(dict)
        self.__paths_by_id = {}
        connectivity_models = kb.connectivity_models()
        for model in connectivity_models:
            model_knowledege = kb.get_knowledge(model)
            for path in model_knowledege['paths']:
                path_knowledge = kb.get_knowledge(path['id'])
                self.__paths_by_id[path['id']] = path_knowledge
                G = connectivity_graph_from_knowledge(path_knowledge)
                if G:
                    path_type = G.graph['path-type']
                    self.__sckan_path_nodes_by_type[path_type][path['id']] = SckanNodeSet(path['id'], G)

    def valid_sckan_paths(self, path_type, end_node_terms):
    #======================================================
        sckan_path_ids = []
        for sckan_path_id, node_set in self.__sckan_path_nodes_by_type[path_type].items():
            if (node_set.has_connector(*end_node_terms[0])
            and node_set.has_connector(*end_node_terms[-1])):
                sckan_path_ids.append(sckan_path_id)
        return sckan_path_ids

#===============================================================================

class SckanConnection:
    def __init__(self, connection, end_node_terms, intermediate_terms):
        self.__connection = connection
        self.__end_node_terms = end_node_terms
        self.__intermediate_terms = intermediate_terms

    @property
    def connection(self):
        return self.__connection

    @property
    def has_feature(self):
        return ('feature' in self.__connection.properties
            and not self.__connection.properties.get('exclude', False))

    def check_validity(self, neuron_checker):
    #========================================
        sckan_path_ids = neuron_checker.valid_sckan_paths(self.__connection.path_type,
                                                          self.__end_node_terms)
        description = {
            'id': self.__connection.id,
            'endNodes': tuple(sorted(self.__end_node_terms)),
            'type': self.__connection.path_type.name
        }
        if len(self.__intermediate_terms):
            description['intermediates'] = self.__intermediate_terms
        feature = self.__connection.properties['feature']
        if len(sckan_path_ids):
            description['sckanPaths'] = sckan_path_ids
            feature.properties['sckan'] = True
            feature.properties['models'] = sckan_path_ids[0]
            label = f"Neuron in '{kb.get_label(sckan_path_ids[0])}'"
            if 'name' in feature.properties:
                label += '\n' + feature.properties.get('name', '')
            feature.properties['label'] = label
        elif not settings.get('invalidNeurons', False):
            feature.properties['exclude'] = True
        return description

#===============================================================================

class SckanNeuronPopulations:
    def __init__(self, flatmap):
        self.__flatmap = flatmap
        self.__annotator_database = AnnotatorDatabase(flatmap.map_dir)
        self.__sckan_connections = []
        self.__connection_descriptions: list[dict] = []

    def generate_connectivity(self):
    #===============================
        neuron_checker = SckanNeuronChecker(self.__flatmap)
        for sckan_connection in self.__sckan_connections:
            if sckan_connection.has_feature:
                description = sckan_connection.check_validity(neuron_checker)
                self.__connection_descriptions.append(description)
                if ((sckan_path_ids := description.get('sckanPaths')) is not None
                  and len(sckan_path_ids) > 1):
                    # If the neuron is in multiple SCKAN populations then add a line feature for each one
                    connection = sckan_connection.connection
                    properties = connection.properties.copy()
                    properties.pop('feature', None)
                    for n, sckan_path_id in enumerate(sckan_path_ids[1:]):
                        properties['id'] = f'connection.id/{n}'
                        properties['models'] = sckan_path_id
                        self.__flatmap.new_feature(connection.geometry, properties)

    def add_connection(self, feature_lookup, connection):
    #====================================================
        end_node_terms = []
        for connector_id in connection.connector_ids:
            properties = feature_lookup(connector_id)
            if (models := properties.get('parent-models')) is not None:
                end_node_terms.append(models)
        intermediate_terms = []
        for component_id in connection.intermediate_components:
            properties = feature_lookup(component_id)
            if (models := properties.get('models')) is not None:
                intermediate_terms.append(models)
        for connector_id in connection.intermediate_connectors:
            properties = feature_lookup(connector_id)
            if (models := properties.get('models')) is not None:
                intermediate_terms.append(models)
        if len(end_node_terms) > 1:
            self.__sckan_connections.append(SckanConnection(connection,
                                                            end_node_terms,
                                                            intermediate_terms))
        elif not settings.get('invalidNeurons', False):
            connection.properties['exclude'] = True

    def connections_with_evidence(self, evidence_urls='http', sckan_missing=True):
    #=============================================================================
        connections = []
        for description in self.__connection_descriptions:
            evidence = self.__annotator_database.get_derivation(description['id'])
            if evidence_urls == 'http':
                evidence = [e for e in evidence if e.startswith('http')]
            if evidence_urls == 'non-http':
                evidence = [e for e in evidence if not e.startswith('http')]
            if (len(evidence)
            and (not sckan_missing
              or sckan_missing and 'sckanPaths' not in description)):
                description['evidence'] = evidence
                connections.append(description)
        return connections

#===============================================================================

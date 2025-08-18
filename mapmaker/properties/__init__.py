#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019  David Brooks
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
from typing import TYPE_CHECKING

#===============================================================================

import mapmaker.knowledgebase as knowledgebase
from mapmaker.routing import Network
from mapmaker.settings import settings, MAP_KIND
from mapmaker.utils import FilePath, log

from .anatomicalmap import AnatomicalMap

# Exports
from .pathways import ConnectionSet, Pathways

if TYPE_CHECKING:
    from mapmaker.flatmap import FlatMap, Manifest

#===============================================================================

class PropertiesStore(object):
    def __init__(self, flatmap: "FlatMap", manifest: "Manifest"):
        self.__flatmap = flatmap
        self.__anatomical_map = AnatomicalMap(manifest.anatomical_map)
        self.__properties_by_class = defaultdict(dict)
        self.__properties_by_id = defaultdict(dict)
        self.__nerve_ids_by_model = {}
        self.__nerve_models_by_id = {}
        if manifest.properties is None:
            properties_dict = {}
        else:
            properties_dict = FilePath(manifest.properties).get_json()
        self.__set_class_properties(properties_dict.get('classes'))
        self.__set_feature_properties(properties_dict.get('features'))

        # Load path definitions in properties' file
        self.__pathways = Pathways(flatmap, properties_dict.get('paths', []))

        # Connectivity defined in JSON
        for connectivity_source in manifest.connectivity:
            connectivity = FilePath(connectivity_source).get_json()
            self.__pathways.add_connectivity(connectivity)

        # ApiNATOMY connectivity models from SciCrunch
        connectivity_models = knowledgebase.connectivity_models()
        seen_npo = False
        for connectivity_source in manifest.neuron_connectivity:
            path_filter = None
            traced_paths = None
            if isinstance(connectivity_source, dict):
                model_source = connectivity_source['uri']
                if (filter_lists := connectivity_source.get('filter')) is not None:
                    include_ids = filter_lists['include'] if 'include' in filter_lists else None
                    exclude_ids = filter_lists['exclude'] if 'exclude' in filter_lists else None
                    if 'trace' in filter_lists:
                        traced_paths = filter_lists['trace']
                        include_ids = traced_paths if include_ids is None else (include_ids + traced_paths)
                    path_filter = lambda path_id: ((include_ids is None or include_ids is not None and path_id in include_ids)
                                               and (exclude_ids is None or exclude_ids is not None and path_id not in exclude_ids))
            else:
                model_source = connectivity_source
            if model_source in connectivity_models:
                self.__pathways.add_connectivity_model(model_source, self,
                    path_filter=path_filter, traced_paths=traced_paths)
            elif model_source == 'NPO':
                # NPO connectivity paths
                if seen_npo:
                    log.warning(f'`NPO` can only be specified once as a connectivity source')
                else:
                    seen_npo = True
                    settings['NPO'] = True
                    for connectivity_path in knowledgebase.connectivity_paths():
                        path_knowledge =  knowledgebase.get_knowledge(connectivity_path)
                        if (path_knowledge.get('pathDisconnected', False) and not settings.get('disconnectedPaths', False)):
                            continue
                        phenotype_sex = path_knowledge.get('biologicalSex')
                        if (manifest.biological_sex is None or phenotype_sex is None
                         or manifest.biological_sex == phenotype_sex):
                            self.__pathways.add_connectivity_path(connectivity_path,
                                self, path_filter=path_filter, traced_paths=traced_paths)

        # Load network centreline definitions
        self.__networks = { network.get('id'): Network(flatmap, network, self)
                                for network in properties_dict.get('networks', []) }

        # Proxy features defined in JSON
        self.__proxies = ([dict(feature=proxy['feature'], proxies=proxy['proxies'])
                           for proxy in FilePath(manifest.proxy_features).get_json()]
                           if manifest.proxy_features is not None
                           else [])

        # Feature groups by layer
        self.__feature_groups: dict[str, dict[str, list[str]]] = {}
        for group_defns in properties_dict.get('feature-groups', []):
            if 'layer' in group_defns:
                feature_groups: dict[str, list[str]] = {}
                for group in group_defns.get('groups', []):
                    if 'id' in group:
                        feature_groups[group['id']] = group.get('features', [])
                self.__feature_groups[group_defns['layer']] = feature_groups

    @property
    def connectivity(self):
        return self.__pathways.connectivity

    @property
    def nerve_ids_by_model(self):
        return self.__nerve_ids_by_model

    @property
    def nerve_models_by_id(self):
        return self.__nerve_models_by_id

    @property
    def pathways(self):
        return self.__pathways

    @property
    def proxies(self):
        return self.__proxies

    @property
    def node_hierarchy(self):
        return self.__pathways.node_hierarchy

    """
    Get the feature group definitions for a layer
    """
    def feature_groups(self, layer_id: str) -> dict[str, list[str]]:
    #==============================================================
        return self.__feature_groups.get(layer_id, {})

    def network_feature(self, feature):
    #==================================
        # Is the ``feature`` included in some network?
        for network in self.__networks.values():
            if network.has_feature(feature):
                return True
        return False

    def __set_class_properties(self, classes):
    #=========================================
        if classes is not None:
            for cls, properties in classes.items():
                self.__properties_by_class[cls].update(properties)

    def __set_feature_properties(self, features):
    #============================================
        if isinstance(features, dict):
            for id, properties in features.items():
                id = id.replace(' ', '_')
                if (associated_details := properties.get('associated-details')) is not None:
                    if isinstance(associated_details, str):
                        properties['associated-details'] = [associated_details]
                self.__properties_by_id[id].update(properties)
                if (properties.get('type') == 'nerve'
                and (entity := properties.get('models')) is not None):
                    if entity in self.__nerve_ids_by_model:
                        log.error(f'Nerve `{entity}` has already been assigned to a feature')
                    else:
                        self.__nerve_ids_by_model[entity] = id
                    if id in self.__nerve_models_by_id:
                        log.error(f'Feature `{id}` has already been assigned a model')
                    else:
                        self.__nerve_models_by_id[id] = entity
        elif features is not None:
            # ``Old`` style of properties
            for feature in features:
                if 'class' in feature:
                    cls = feature['class']
                    properties = feature.get('properties', {})
                    self.__properties_by_class[cls].update(properties)
                if 'id' in feature:
                    id = feature['id']
                    properties = feature.get('properties', {})
                    self.__properties_by_id[id].update(properties)

    def generate_connectivity(self):
    #===============================
        for network in self.__networks.values():
            network.check_features_on_map()
        self.__pathways.generate_connectivity(self.__networks.values())

    def get_property(self, id, key):
    #===============================
        return self.properties(id).get(key)

    def set_property(self, id, key, value):
    #======================================
        self.__properties_by_id[id][key] = value

    def properties(self, id):
    #========================
        properties = {'id': id}
        properties.update(self.__properties_by_id.get(id, {}))
        self.update_properties(properties)
        return properties

    def update_properties(self, feature_properties):
    #===============================================
        classes = feature_properties.get('class', '').split()
        id = feature_properties.get('id')
        if self.__flatmap.map_kind == MAP_KIND.FUNCTIONAL and id not in self.__properties_by_id:
            # Use the feature's name to lookup properties when the feature has no ID
            if (name := feature_properties.get('name', '').replace(' ', '_')) != '':
                id = f'{feature_properties.get('layer', '')}/{name}'
        if id is not None:
            classes.extend(self.__properties_by_id.get(id, {}).get('class', '').split())
        for cls in classes:
            feature_properties.update(self.__anatomical_map.properties(cls))
            feature_properties.update(self.__properties_by_class.get(cls, {}))
        if id is not None:         # id overrides class
            feature_properties.update(self.__anatomical_map.properties(id))
            feature_properties.update(self.__properties_by_id.get(id, {}))
        self.__pathways.update_line_or_nerve_properties(feature_properties)

        if 'marker' in feature_properties:
            feature_properties['type'] = 'marker'
            if 'datasets' in feature_properties:
                feature_properties['kind'] = 'dataset'
            elif 'scaffolds' in feature_properties:
                feature_properties['kind'] = 'scaffold'
            elif 'simulations' in feature_properties:
                feature_properties['kind'] = 'simulation'

        # Only separately show name when authoring FC map
        name_used = self.__flatmap.map_kind != MAP_KIND.FUNCTIONAL
        if (entity := feature_properties.get('models')) is not None and entity.strip() != '':
            # Make sure our knowledgebase knows about the anatomical object
            knowledge = knowledgebase.get_knowledge(entity)
            label = knowledge.get('label')
            if label == entity and (source_label := feature_properties.get('label', '')):
                feature_properties['label'] = source_label
            elif settings.get('authoring', False):
                feature_properties['label'] = f'{label} ({entity})'
            else:
                feature_properties['label'] = label
            # FC neuron path with connection information in name
            if feature_properties.get('population', False):
                label = f"Neuron in '{feature_properties['label']}'"
                if 'name' in feature_properties:
                     label += '\n' + feature_properties.get('name', '')
                feature_properties['label'] = label
            if (taxons := knowledge.get('taxons')) is not None:
                feature_properties['taxons'] = taxons if isinstance(taxons, list) else [taxons]
        elif 'label' not in feature_properties and 'name' in feature_properties:
            feature_properties['label'] = feature_properties['name']
            name_used = True

        if settings.get('authoring', False):
            # Show id and classes in label if authoring
            labels = []
            if (label := feature_properties.get('label', '')):
                labels.append(label)
            if not name_used and (name := feature_properties.get('name')):
                labels.append(f'Name: {name}')
            if len(classes):
                labels.append(f'Class: {", ".join(classes)}')
            if len(labels):  # We don't want empty tooltips
                feature_properties['label'] = '\n'.join(labels)
        elif 'label' in feature_properties and feature_properties['label'] in [None, '']:
            del feature_properties['label']   # So empty values doesn't get passed to the viewer

        if feature_properties.get('centreline', False) and feature_properties.get('node', False):
            log.error(f'Feature `{id}` cannot be both a centreline and a node')

        ## Put network features and centrelines on their own MapLayer called say "Nerves"
        ## if AC map??

        return feature_properties

#===============================================================================

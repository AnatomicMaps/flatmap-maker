#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019, 2020  David Brooks
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

from __future__ import annotations
from collections import defaultdict
from typing import Any, Optional

from shapely.geometry.base import BaseGeometry

#===============================================================================

from mapmaker.knowledgebase import get_label
from mapmaker.utils import log, FilePath

#===============================================================================

def entity_name(entity):
    if entity is None:
        return 'None'
    return get_label(entity)

def full_node_name(anatomical_id, anatomical_layers):
    if len(anatomical_layers) == 0:
        return entity_name(anatomical_id)
    else:
        layer_names = ', '.join([entity_name(entity) for entity in anatomical_layers if entity is not None])
        return f'{entity_name(anatomical_id)} in {layer_names}'

#===============================================================================

class Feature(object):
    def __init__(self, geojson_id: int,
                       geometry: BaseGeometry,
                       properties: dict[str, Any],
                       has_children:bool=False):
        self.__geojson_id = geojson_id     # Must be numeric for tipeecanoe
        self.__geometry = geometry
        self.__properties = properties.copy()
        self.__properties['featureId'] = geojson_id   # Used by flatmap viewer
        self.__properties['geometry'] = geometry.geom_type
        self.__has_children = has_children

    def __str__(self):
        return 'Feature: {}, {}'.format(self.__geometry.geom_type,
            { k:v for k, v in self.__properties.items() if k != 'bezier-segments'})

    @property
    def geojson_id(self) -> int:
        return self.__geojson_id

    @property
    def geom_type(self) -> str:
        return self.__geometry.geom_type if self.__geometry else None

    @property
    def geometry(self) -> BaseGeometry:
        return self.__geometry

    @geometry.setter
    def geometry(self, geometry: BaseGeometry):
        self.__geometry = geometry

    @property
    def has_children(self) -> bool:
        return self.__has_children

    @property
    def id(self) -> Optional[str]:
        return self.__properties.get('id')

    @property
    def models(self) -> Optional[str]:
        return self.__properties.get('models')

    @property
    def properties(self) -> dict[str, Any]:
        return self.__properties

    def visible(self) -> bool:
        return not self.property('invisible')

    def del_property(self, key: str) -> Any:
        if key in self.__properties:
            return self.__properties.pop(key)

    def property(self, key: str, default: Any=None) -> Any:
        return self.__properties.get(key, default)

    def has_property(self, key: str) -> bool:
        return self.__properties.get(key, '') != ''

    def set_property(self, key: str, value: Any) -> None:
        if value is None:
            self.del_property(key)
        else:
            self.__properties[key] = value

#===============================================================================

class FeatureMap(object):
    def __init__(self, connectivity_terms=None):
        self.__connectivity_terms = {}
        if connectivity_terms is not None:
            equivalences = FilePath(connectivity_terms).get_json()
            for equivalence in equivalences:
                term = equivalence['id']
                for alias in equivalence.get('aliases', []):
                    if alias in self.__connectivity_terms:
                        log.error(f'Connectivity term {alias} cannot map to both {self.__connectivity_terms[alias]} and {term}')
                    else:
                        self.__connectivity_terms[alias] = term
        self.__id_to_feature = {}
        self.__model_to_features = defaultdict(list)

    def add_feature(self, feature):
    #==============================
        if feature.id is not None:
            if feature.id in self.__id_to_feature:
                log.error(f'Duplicate feature id: {feature.id}')
            else:
                self.__id_to_feature[feature.id] = feature
        if feature.models is not None:
            self.__model_to_features[feature.models].append(feature)

    def duplicate_id(self, id):
    #==========================
        return self.__id_to_feature.get(id, None) is not None

    def find_path_features_by_anatomical_id(self, anatomical_id, anatomical_layers):
    #===============================================================================
        def features_from_anatomical_id(term):
            return set(self.__model_to_features.get(self.__connectivity_terms.get(term, term), []))

        anatomical_layers = list(anatomical_layers)
        if len(anatomical_layers) == 0:
            return features_from_anatomical_id(anatomical_id)
        else:
            features = features_from_anatomical_id(anatomical_id)
            if len(features) == 0:
                while len(anatomical_layers) > 0:
                    substitute_id = anatomical_layers.pop(0)
                    features = features_from_anatomical_id(substitute_id)
                    if len(features):
                        log.warning(f'Cannot find feature for {entity_name(anatomical_id)} ({anatomical_id}), substituted containing `{entity_name(substitute_id)}` region')
                        break
            if len(features) == 1 or len(anatomical_layers) == 0:
                return features

            # Check feature is contained in specified layers
            for anatomical_layer in anatomical_layers:
                included_features = set()
                layer_features = features_from_anatomical_id(anatomical_layer)
                for layer_feature in layer_features:
                    for feature in features:
                        if layer_feature.geometry.contains(feature.geometry.centroid):
                            included_features.add(feature)
                anatomical_features = included_features
                if len(included_features) == 1:
                    break
        return anatomical_features

    def geojson_ids(self, ids):
    #==========================
        return [f.geojson_id for id in ids if (f := self.__id_to_feature.get(id)) is not None]

    def get_feature(self, id):
    #=========================
        return self.__id_to_feature.get(id)

    def has_feature(self, id):
    #=========================
        return id in self.__id_to_feature

#===============================================================================

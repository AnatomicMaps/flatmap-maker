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
from typing import Any, NewType, Optional

from shapely.geometry.base import BaseGeometry

#===============================================================================

from mapmaker.knowledgebase import AnatomicalNode, entity_name
from mapmaker.utils import log, FilePath, PropertyMixin

#===============================================================================

EXCLUDE_PROPERTIES_FROM_STR = [
    'bezier-segments',
    'pptx-shape',
    'svg-element'
]

class Feature(PropertyMixin):
    def __init__(self, geojson_id: int,
                       geometry: BaseGeometry,
                       properties: dict[str, Any],
                       is_group:bool=False):
        super().__init__(properties)
        self.__geojson_id = geojson_id     # Must be numeric for tipeecanoe
        self.__geometry = geometry
        self.properties['featureId'] = geojson_id   # Used by flatmap viewer
        self.properties['geometry'] = geometry.geom_type
        self.__is_group = is_group

    def __eq__(self, other):
        return isinstance(other, Feature) and self.__geojson_id == other.__geojson_id

    def __hash__(self):
        return hash(self.geojson_id)

    def __str__(self):
        return 'Feature {}: {}, {}'.format(self.__geojson_id, self.__geometry.geom_type,
            { k:v for k, v in self.properties.items() if k not in EXCLUDE_PROPERTIES_FROM_STR })

    @property
    def geojson_id(self) -> int:
        return self.__geojson_id

    @property
    def geom_type(self) -> Optional[str]:
        return self.__geometry.geom_type if self.__geometry else None

    @property
    def geometry(self) -> BaseGeometry:
        return self.__geometry

    @geometry.setter
    def geometry(self, geometry: BaseGeometry):
        self.__geometry = geometry

    @property
    def id(self) -> Optional[str]:
        return self.get_property('id')

    @property
    def is_group(self) -> bool:
        return self.__is_group

    @property
    def models(self) -> Optional[str]:
        return self.get_property('models')

    def visible(self) -> bool:
        return not self.get_property('invisible')

#===============================================================================

class FeatureAnatomicalNodeMap:
    def __init__(self, terms_alias_file: Optional[str]=None):
        self.__anatomical_aliases: dict[str|tuple, str] = {}
        if terms_alias_file is not None:
            equivalences = FilePath(terms_alias_file).get_json()
            for equivalence in equivalences:
                term = equivalence['id']
                term = (term[0], tuple(term[1])) if isinstance(term, list) else term
                for alias in equivalence.get('aliases', []):
                    alias = (alias[0], tuple(alias[1])) if isinstance(alias, list) else alias
                    if alias in self.__anatomical_aliases:
                        log.error(f'Alias {alias} cannot map to both {self.__anatomical_aliases[alias]} and {term}')
                    else:
                        self.__anatomical_aliases[alias] = term
        self.__model_to_features: dict[str, set[Feature]] = defaultdict(set)

    def add_feature(self, feature: Feature):
    #=======================================
        if feature.models is not None:
            self.__model_to_features[feature.models].add(feature)

    def features_for_anatomical_node(self, anatomical_node: AnatomicalNode, warn: bool=True) -> tuple[AnatomicalNode, set[Feature]]:
    #===============================================================================================================================
        def features_from_anatomical_id(term: str) -> set[Feature]:
            return set(self.__model_to_features.get(self.__anatomical_aliases.get(term, term), []))

        if anatomical_node in self.__anatomical_aliases:
            anatomical_node = AnatomicalNode(self.__anatomical_aliases[anatomical_node])

        anatomical_id = anatomical_node[0]
        features = features_from_anatomical_id(anatomical_id)
        layers = list(anatomical_node[1])
        if len(layers) == 0:
            return (anatomical_node, features)

        # Remove any nerve features from the anatomical node's layers
        anatomical_layers = []
        for layer in layers:
            nerve_layer = False
            for feature in features_from_anatomical_id(layer):
                if feature.get_property('type') == 'nerve':
                    nerve_layer = True
                    break
            if not nerve_layer:
                anatomical_layers.append(layer)

        # Look for a substitute feature if we can't find the base term
        matched_node = AnatomicalNode([anatomical_id, anatomical_layers])
        if len(features) == 0:
            while len(anatomical_layers) > 0:
                substitute_id = anatomical_layers.pop(0)
                features = features_from_anatomical_id(substitute_id)
                if len(features):
                    if warn:
                        log.warning(f'Cannot find feature for `{entity_name(anatomical_id)}` ({anatomical_id}), substituted containing `{entity_name(substitute_id)}` region')
                    matched_node = AnatomicalNode([substitute_id, anatomical_layers])
                    break
        if len(anatomical_layers) == 0:
            return (matched_node, features)

        # Restrict found features to those contained in specified layers
        matched_features = set()
        for feature in features:
            feature_in_layers = False
            for anatomical_layer in anatomical_layers:
                feature_in_layer = False
                for layer_feature in features_from_anatomical_id(anatomical_layer):
                    if layer_feature.geometry.contains(feature.geometry.centroid):
                        feature_in_layer = True
                        break
                if feature_in_layer:
                    feature_in_layers = True
                    break
            if feature_in_layers:
                matched_features.add(feature)
        if len(matched_features) == 0 and len(features) == 1:
            matched_features = features
            if warn:
                log.warning(f'Feature `{matched_node.full_name}` is not in expected layers')
        return (matched_node, matched_features)

#===============================================================================

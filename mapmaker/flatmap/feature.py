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

from collections import defaultdict
import json
import typing
from typing import Any, Optional, TYPE_CHECKING

from shapely.geometry.base import BaseGeometry
import structlog

#===============================================================================

from mapmaker.geometry import MapBounds
from mapmaker.knowledgebase import AnatomicalNode, entity_name
from mapmaker.utils import log, FilePath, PropertyMixin

if TYPE_CHECKING:
    from .layers import MapLayer

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
        self.__anatomical_nodes: set[str] = set()
        self.__geojson_id = geojson_id     # Must be numeric for tipeecanoe
        self.__geometry = geometry
        self.properties['featureId'] = geojson_id   # Used by flatmap viewer
        self.properties['geometry'] = geometry.geom_type
        self.__is_group = is_group
        self.__layer = None

    def __eq__(self, other):
        return isinstance(other, Feature) and self.__geojson_id == other.__geojson_id

    def __hash__(self):
        return hash(self.geojson_id)

    def __str__(self):
        return 'Feature {}: {}, {}'.format(self.__geojson_id, self.__geometry.geom_type,
            { k:v for k, v in self.properties.items() if k not in EXCLUDE_PROPERTIES_FROM_STR })

    @property
    def anatomical_nodes(self) -> list[str]:
        return list(self.__anatomical_nodes)
    def add_anatomical_node(self, node: AnatomicalNode):
        self.__anatomical_nodes.add(json.dumps(node))

    @property
    def bounds(self) -> MapBounds:
        return self.__geometry.bounds

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
    def layer(self) -> Optional['MapLayer']:
        return self.__layer

    @layer.setter
    def layer(self, layer: Optional['MapLayer']):
        self.__layer = layer

    @property
    def models(self) -> Optional[str]:
        return self.get_property('models')

    def visible(self) -> bool:
        return not self.get_property('invisible')

#===============================================================================

class FeatureAnatomicalNodeMap:
    def __init__(self, terms_alias_file: Optional[str]=None):
        self.__anatomical_aliases: dict[str|tuple, tuple] = {}
        self.__log = typing.cast(structlog.BoundLogger, log.bind(type='feature'))
        if terms_alias_file is not None:
            equivalences = FilePath(terms_alias_file).get_json()
            for equivalence in equivalences:
                term = equivalence['id']
                term = (term[0], tuple(term[1])) if isinstance(term, list) else term
                for alias in equivalence.get('aliases', []):
                    alias = (alias[0], tuple(alias[1])) if isinstance(alias, list) else alias
                    if alias in self.__anatomical_aliases:
                        self.__log.error('Alias cannot map to both terms, alias=alias, terms=[self.__anatomical_aliases[alias], term]')
                    else:
                        self.__anatomical_aliases[alias] = term
        self.__model_to_features: dict[str|tuple, set[Feature]] = defaultdict(set)

    def add_feature(self, feature: Feature):
    #=======================================
        if feature.models is not None:
            self.__model_to_features[feature.models].add(feature)

    def features_for_anatomical_node(self, anatomical_node: AnatomicalNode, warn: bool=False) -> tuple[AnatomicalNode, set[Feature]]:
    #================================================================================================================================
        def features_from_anatomical_id(term: str|tuple) -> set[Feature]:
            return set(self.__model_to_features.get(self.__anatomical_aliases.get(term, term), []))
        def save_anatomical_node(features):
            for feature in features:
                feature.add_anatomical_node(anatomical_node)

        if anatomical_node in self.__anatomical_aliases:
            anatomical_node = AnatomicalNode(self.__anatomical_aliases[anatomical_node])

        anatomical_id = anatomical_node[0]
        features = features_from_anatomical_id(anatomical_id)
        layers = list(anatomical_node[1])
        if len(layers) == 0:
            save_anatomical_node(features)
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
                        self.__log.warning('Cannot find feature for entity, substituted containing region',
                                        name=entity_name(anatomical_id), entity=anatomical_id,
                                        substitute=entity_name(substitute_id))
                    matched_node = AnatomicalNode([substitute_id, anatomical_layers])
                    break
        if len(anatomical_layers) == 0:
            save_anatomical_node(features)
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
                self.__log.warning(f'Feature is not in expected layers', feature=matched_node.full_name)

        save_anatomical_node(matched_features)
        return (matched_node, matched_features)

    def get_features(self, model: str) -> set[Feature]:
    #==================================================
        return self.__model_to_features.get(model, set())

    def has_model(self, model: str) -> bool:
    #=======================================
        return model in self.__model_to_features

#===============================================================================

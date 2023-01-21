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
from collections import OrderedDict
import datetime
import os
from typing import Optional

#===============================================================================

import cv2
import numpy as np

#===============================================================================

from mapmaker import FLATMAP_VERSION, __version__
from mapmaker.geometry import FeatureSearch, Transform
from mapmaker.geometry import normalised_coords
from mapmaker.knowledgebase import get_knowledge
from mapmaker.properties import ConnectorSet, ExternalProperties
from mapmaker.settings import settings
from mapmaker.utils import log

from .feature import Feature, FeatureMap
from .layers import MapLayer

#===============================================================================

class FlatMap(object):
    def __init__(self, manifest, maker):
        self.__id = maker.id
        self.__uuid = maker.uuid
        self.__map_dir = maker.map_dir
        self.__manifest = manifest
        self.__local_id = manifest.id
        self.__models = manifest.models
        self.__extent = None
        self.__centre = None
        self.__min_zoom = maker.zoom[0]
        self.__feature_map = None

    def __len__(self):
        return self.__visible_layer_count

    @property
    def annotations(self):
        return self.__annotations

    @property
    def area(self):
        return self.__area

    @property
    def centre(self):
        return self.__centre

    @property
    def created(self):
        return self.__created

    @property
    def extent(self):
        return self.__extent

    @property
    def entities(self):
        return self.__entities

    @property
    def feature_map(self):
        return self.__feature_map

    @property
    def id(self):
        return self.__id

    @property
    def layer_ids(self):
        return list(self.__layer_dict.keys())

    @property
    def layers(self):
        return self.__layer_dict.values()

    @property
    def local_id(self):
        return self.__local_id

    @property
    def map_properties(self):
        return self.__map_properties

    @property
    def metadata(self):
        return self.__metadata

    @property
    def models(self):
        return self.__models

    @property
    def uuid(self):
        return self.__uuid

    def initialise(self):
    #====================
        self.__created = None   # Set when map closed
        self.__metadata = {
            'id': self.__id,
            'uuid': self.__uuid,
            'name': self.__local_id,
            # Who made the map
            'creator': 'mapmaker {}'.format(__version__),
            # The URL of the map's manifest
            'source': self.__manifest.url,
            'version': FLATMAP_VERSION
        }
        if self.__models is not None:
            self.__metadata['taxon'] = self.__models
            if (sex := self.__manifest.biological_sex) is not None:
                self.__metadata['biological-sex'] = sex
            knowledge = get_knowledge(self.__models)
            if 'label' in knowledge:
                self.__metadata['describes'] = knowledge['label']

        self.__entities = set()

        # Properties about map features
        self.__map_properties = ExternalProperties(self, self.__manifest)

        self.__layer_dict = OrderedDict()
        self.__visible_layer_count = 0

        self.__annotations = {}

        self.__feature_map = FeatureMap(self.__manifest.connectivity_terms)
        self.__features = OrderedDict()
        self.__last_geojson_id = 0

        # Used to find annotated features containing a region
        self.__feature_search = None

    def close(self):
    #===============
        # Add high-resolution features showing details
        self.__add_details()
        # Set additional properties from properties file
        self.__set_feature_properties()
        # Initialise geographical search for annotated features
        self.__setup_feature_search()
        # Generate metadata with connection information
        self.__resolve_connectivity()
        # Set creation time
        self.__created = datetime.datetime.utcnow()
        self.__metadata['created'] = self.__created.isoformat()

    def full_filename(self, localname):
    #==================================
        return os.path.join(self.__map_dir, localname)

    def is_duplicate_feature_id(self, feature_id: str) -> bool:
    #==========================================================
        return self.__feature_map is not None and self.__feature_map.duplicate_id(feature_id)

    def save_feature_for_lookup(self, feature: Feature):
    #===================================================
        if self.__feature_map is not None:
            self.__feature_map.add_feature(feature)

    def get_feature(self, feature_id: str) -> Optional[Feature]:
    #===========================================================
        return self.__features.get(feature_id)

    def new_feature(self, geometry, properties, has_children=False):
    #===============================================================
        self.__last_geojson_id += 1
        feature = Feature(self.__last_geojson_id, geometry, properties, has_children)
        self.__features[self.__last_geojson_id] = feature
        return feature

    def feature_exported(self, feature):
    #===================================
        return (not settings.get('onlyNetworks', False)
             or self.__map_properties.network_feature(feature))

    def add_layer(self, layer):
    #==========================
        if layer.id in self.__layer_dict:
            raise KeyError('Duplicate layer id: {}'.format(layer.id))
        self.__layer_dict[layer.id] = layer
        if layer.exported:
            self.__visible_layer_count += 1
            if settings.get('showCentrelines', False):
                connector_set = ConnectorSet('centreline')
                for feature in layer.features:
                    if (feature.properties.get('centreline', False)
                      and not feature.properties.get('excluded', False)):
                        feature.set_property('kind', 'centreline')
                        feature.set_property('tile-layer', 'pathways')
                        connector_set.add(feature.properties['id'],
                                          feature.properties['kind'],
                                          feature.geojson_id)
                self.map_properties.pathways.add_connector_set(connector_set)

    def add_source_layers(self, layer_number, source):
    #=================================================
        for layer in source.layers:
            self.add_layer(layer)
            if layer.exported:
                layer.add_raster_layer(layer.id, source.extent, source, self.__min_zoom)
        # The first layer is used as the base map
        if layer_number == 0:
            if source.kind == 'details':
                raise ValueError('Details layer cannot be the base map')
            self.__extent = source.extent
            self.__centre = ((self.__extent[0] + self.__extent[2])/2,
                             (self.__extent[1] + self.__extent[3])/2)
            self.__area = source.map_area()
        elif source.kind not in ['details', 'image', 'layer']:
            raise ValueError('Can only have a single base map')

    def layer_metadata(self):
    #========================
        metadata = []
        for layer in self.__layer_dict.values():
            if layer.exported:
                map_layer = {
                    'id': layer.id,
                    'description': layer.description,
                    'image-layers': [source.id for source in layer.raster_layers]
                }
                metadata.append(map_layer)
        return metadata

    def update_annotations(self, annotations):
    #=========================================
        for properties in annotations.values():
            if 'models' in properties:
                self.__entities.add(properties['models'])
        self.__annotations.update(annotations)

    def __set_feature_properties(self):
    #==================================
        for layer in self.__layer_dict.values():
            layer.set_feature_properties(self.__map_properties)

    def __add_details(self):
    #=======================
        # Add details of high-resolution features by adding a details layer
        # for features with details

        ## Need image layers...
        ##
        ## have Image of slide with outline image and outline's BBOX
        ## so can get Rect with just outline. Transform to match detail's feature.
        ##
        ## set layer.__image from slide when first making??
        ## Also want image layers scaled and with minzoom set...

        log('Adding details...')
        detail_layers = []
        for layer in self.__layer_dict.values():
            if layer.exported and layer.detail_features:
                detail_layer = MapLayer('{}_details'.format(layer.id), layer.source, exported=True)
                detail_layers.append(detail_layer)
                self.__add_detail_features(layer, detail_layer, layer.detail_features)
        for layer in detail_layers:
            self.add_layer(layer)

## Put all this into 'features.py' as a function??
    def __new_detail_feature(self, layer_id, detail_layer, minzoom, geometry, properties):
    #=====================================================================================
        new_feature = self.new_feature(geometry, properties)
        new_feature.set_property('layer', layer_id)
        new_feature.set_property('minzoom', minzoom)
        if properties.get('type') == 'nerve':
            new_feature.set_property('type', 'nerve-section')
            new_feature.set_property('nerveId', new_feature.geojson_id)  # Used in map viewer
            ## Need to link outline feature of nerve into paths through the nerve so it is highlighted
            ## when mouse over a path through the nerve
            new_feature.set_property('tile-layer', 'pathways')
        detail_layer.add_feature(new_feature)
        return new_feature

    def __add_detail_features(self, layer, detail_layer, lowres_features):
    #=====================================================================
        extra_details = []
        for feature in lowres_features:
            self.__map_properties.update_feature_properties(feature)
            hires_layer_id = feature.property('details')
            hires_layer = self.__layer_dict.get(hires_layer_id)
            if hires_layer is None:
                log.warning("Cannot find details layer '{}'".format(feature.property('details')))
                continue
            boundary_feature = hires_layer.boundary_feature
            if boundary_feature is None:
                raise KeyError("Cannot find boundary of '{}' layer".format(hires_layer.id))

            # Calculate transformation to map source shapes to the destination

            # NOTE: We reorder the coordinates of the bounding rectangles so that the first
            #       coordinate is the top left-most one. This should ensure that the source
            #       and destination rectangles align as intended, without output features
            #       being rotated by some multiple of 90 degrees.
            src = np.array(normalised_coords(boundary_feature.geometry.minimum_rotated_rectangle), dtype="float32")
            dst = np.array(normalised_coords(feature.geometry.minimum_rotated_rectangle), dtype="float32")
            transform = Transform(cv2.getPerspectiveTransform(src, dst))        # type: ignore

            minzoom = feature.property('maxzoom') + 1
            if feature.property('type') != 'nerve':
                # Set the feature's geometry to that of the high-resolution outline
                feature.geometry = transform.transform_geometry(boundary_feature.geometry)
            else:                             # nerve
                feature.del_property('maxzoom')

            if hires_layer.source.raster_source is not None:
                extent = transform.transform_extent(hires_layer.source.extent)
                layer.add_raster_layer('{}_{}'.format(detail_layer.id, hires_layer.id),
                                        extent, hires_layer.source, minzoom,
                                        local_world_to_base=transform)

            # The detail layer gets a scaled copy of each high-resolution feature
            for hires_feature in hires_layer.features:
                new_feature = self.__new_detail_feature(layer.id, detail_layer, minzoom,
                                                        transform.transform_geometry(hires_feature.geometry),
                                                        hires_feature.properties)
                if new_feature.has_property('details'):
                    extra_details.append(new_feature)

        # If hires features that we've just added also have details then add them
        # to the detail layer
        if extra_details:
            self.__add_detail_features(layer, detail_layer, extra_details)

    def connectivity(self):
    #======================
        return self.__map_properties.connectivity

    def __resolve_connectivity(self):
    #================================
        # Route paths and set feature ids of path components
        self.__map_properties.generate_connectivity(self.__feature_map)

    def __setup_feature_search(self):
    #================================
        annotated_features = []
        for layer in self.__layer_dict.values():
            if layer.exported:
                annotated_features.extend([f for f in layer.features
                                              if f.models is not None
                                                and 'Polygon' in f.geom_type])
        self.__feature_search = FeatureSearch(annotated_features)

    def features_covering(self, feature):
    #====================================
        if self.__feature_search is not None:
            return self.__feature_search.features_covering(feature)
        log.error("Feature search hasn't been initialised")
        return []

    def features_inside(self, feature):
    #==================================
        if self.__feature_search is not None:
            return self.__feature_search.features_inside(feature)
        log.error("Feature search hasn't been initialised")
        return []

#===============================================================================
# Keep layers (and hence features)

# Need to find feature by anatomical id

# Need feature metadata as RDF

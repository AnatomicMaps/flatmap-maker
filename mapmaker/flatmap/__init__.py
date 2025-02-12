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

from collections import OrderedDict
from datetime import datetime, timezone
import os
from typing import Optional, TYPE_CHECKING

#===============================================================================

import cv2                  # type: ignore
import numpy as np          # type: ignore

#===============================================================================

from mapmaker import FLATMAP_VERSION, __version__
from mapmaker.geometry import FeatureSearch, Transform
from mapmaker.geometry import normalised_coords
from mapmaker.geometry.proxy_dot import proxy_dot
from mapmaker.flatmap.layers import PATHWAYS_TILE_LAYER
from mapmaker.knowledgebase import AnatomicalNode, get_knowledge
from mapmaker.knowledgebase.sckan import SckanNeuronPopulations
from mapmaker.properties import ConnectionSet, PropertiesStore
from mapmaker.settings import MAP_KIND, settings
from mapmaker.utils import log

from .feature import Feature, FeatureAnatomicalNodeMap
from .layers import FEATURES_TILE_LAYER, MapLayer

# Exports
from .manifest import Manifest, SourceBackground, SourceManifest

if TYPE_CHECKING:
    from mapmaker.annotation import Annotator
    from mapmaker.maker import MapMaker
    from mapmaker.sources import MapSource

#===============================================================================

SOURCE_DETAIL_KINDS = ['anatomical', 'detail', 'functional']

#===============================================================================

class FlatMap(object):
    def __init__(self, manifest: Manifest, maker: 'MapMaker', annotator: Optional['Annotator']=None):
        self.__id = maker.id
        self.__uuid = maker.uuid
        self.__map_dir = maker.map_dir
        self.__map_kind = (MAP_KIND.FUNCTIONAL if manifest.kind == 'functional'
                      else MAP_KIND.CENTRELINE if manifest.kind == 'centreline'
                      else MAP_KIND.ANATOMICAL)
        self.__manifest = manifest
        self.__local_id = manifest.id
        self.__models = manifest.models
        self.__extent = None
        self.__centre = None
        self.__min_zoom = maker.zoom[0]
        self.__max_zoom = maker.zoom[1]
        self.__annotations = {}
        self.__annotator = annotator
        self.__connection_set = ConnectionSet('connections')
        self.__sckan_provenance = maker.sckan_provenance
        self.__sckan_neuron_populations = SckanNeuronPopulations(self)
        self.__layer_dict: OrderedDict[str, MapLayer] = OrderedDict()
        self.__bottom_exported_layer: Optional[MapLayer] = None

    def __len__(self):
        return self.__visible_layer_count

    @property
    def annotations(self):
        return self.__annotations

    @property
    def annotator(self):
        return self.__annotator

    @property
    def area(self):
        return self.__area

    @property
    def centre(self):
        return self.__centre

    @property
    def connection_set(self):
        return self.__connection_set

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
    def id(self):
        return self.__id

    @property
    def layer_ids(self) -> list[str]:
        return list(self.__layer_dict.keys())

    @property
    def layers(self):
        return self.__layer_dict.values()

    @property
    def local_id(self):
        return self.__local_id

    @property
    def manifest(self):
        return self.__manifest

    @property
    def map_dir(self):
        return self.__map_dir

    @property
    def map_kind(self) -> MAP_KIND:
        return self.__map_kind

    @property
    def max_zoom(self):
        return self.__max_zoom

    @property
    def min_zoom(self):
        return self.__min_zoom

    @property
    def properties_store(self):
        return self.__properties_store

    @property
    def metadata(self):
        return self.__metadata

    @property
    def models(self):
        return self.__models

    @property
    def sckan_neuron_populations(self):
        return self.__sckan_neuron_populations

    @property
    def uuid(self):
        return self.__uuid

    def initialise(self):
    #====================
        self.__created = None   # Set when map closed
        self.__metadata = {
            'id': self.__id,
            'name': self.__local_id,
            # Who made the map
            'creator': 'mapmaker {}'.format(__version__),
            # The URL of the map's manifest
            'source': self.__manifest.url,
            'version': FLATMAP_VERSION
        }
        if len(self.__sckan_provenance):
            self.__metadata['connectivity'] = self.__sckan_provenance
        if self.__uuid is not None:
            self.__metadata['uuid'] = self.__uuid
        if self.__models is not None:
            self.__metadata['taxon'] = self.__models
            if (sex := self.__manifest.biological_sex) is not None:
                self.__metadata['biological-sex'] = sex
            knowledge = get_knowledge(self.__models)
            if 'label' in knowledge:
                self.__metadata['describes'] = knowledge['label']

        self.__entities = set()

        # Properties about map features
        self.__properties_store = PropertiesStore(self, self.__manifest)

        self.__layer_dict = OrderedDict()
        self.__visible_layer_count = 0

        self.__annotations = {}

        self.__feature_node_map = FeatureAnatomicalNodeMap(self.__manifest.connectivity_terms)
        self.__features_with_id: dict[str, Feature] = {}
        self.__features_with_name: dict[str, Feature] = {}
        self.__last_geojson_id = 0
        self.__features_by_geojson_id: dict[int, Feature] = {}

        # Used to find annotated features containing a region
        self.__feature_search = None

    def close(self):
    #===============
        # Add high-resolution features showing details
        self.__add_details()
        # Set additional properties from properties file
        self.__set_feature_properties()
        # Add features to indicate proxies (NB. has to be after setting feature properties)
        self.__add_proxied_features()
        # Initialise geographical search for annotated features
        self.__setup_feature_search()
        # Add manual connections into the map's paths
        self.properties_store.pathways.add_connection_set(self.__connection_set)

        if not settings.get('ignoreSckan', False):
            # Generate connectivity and associated metadata
            self.__generate_connectivity()
        # Set creation time
        self.__created = datetime.now(tz=timezone.utc)
        self.__metadata['created'] = self.__created.isoformat(timespec='seconds')

    def full_filename(self, localname) -> str:
    #=========================================
        return os.path.join(self.__map_dir, localname)

    def save_feature_for_node_lookup(self, feature: Feature):
    #========================================================
        if self.__feature_node_map is not None:
            self.__feature_node_map.add_feature(feature)

    def features_for_anatomical_node(self, anatomical_node: AnatomicalNode, warn: bool=True) -> Optional[tuple[AnatomicalNode, set[Feature]]]:
    #=========================================================================================================================================
        if self.__feature_node_map is not None:
            if len((features:=self.__feature_node_map.features_for_anatomical_node(anatomical_node, warn=warn))[1]) > 0:
                return features
            if len(fts:=set(feature for feature in self.__features_with_id.values()
                            if feature.models in [features[0][0]]+list(features[0][1])
                            and feature.get_property('kind')=='proxy')) > 0:
                return (anatomical_node, fts)
            return features

    def duplicate_feature_id(self, feature_ids: str) -> bool:
    #========================================================
        return self.__features_with_id.get(feature_ids, None) is not None

    def feature_to_geojson_ids(self, feature_ids: list[str]) -> list[int]:
    #=====================================================================
        return [f.geojson_id for id in feature_ids
            if (f := self.__features_with_id.get(id)) is not None]

    def has_feature(self, feature_id: str) -> bool:
    #==============================================
        return feature_id in self.__features_with_id

    def get_feature(self, feature_id: str) -> Optional[Feature]:
    #===========================================================
        return self.__features_with_id.get(feature_id)

    def get_feature_by_name(self, full_name: str) -> Optional[Feature]:
    #==================================================================
        return self.__features_with_name.get(full_name.replace(" ", "_"))

    def get_feature_by_geojson_id(self, geojson_id: int) -> Optional[Feature]:
    #=========================================================================
        return self.__features_by_geojson_id.get(geojson_id)

    def new_feature(self, layer_id: str, geometry, properties, is_group=False) -> Feature:
    #=====================================================================================
        self.__last_geojson_id += 1
        self.properties_store.update_properties(properties)   # Update from JSON properties file
        feature = Feature(self.__last_geojson_id, geometry, properties, is_group=is_group)
        feature.set_property('layer', layer_id)
        if (name := properties.get('name', properties.get('label', ''))) != '':
            self.__features_with_name[f'{layer_id}/{name.replace(" ", "_")}'] = feature
        self.__features_by_geojson_id[feature.geojson_id] = feature
        if feature.id:
            if feature.id in self.__features_with_id:
                pass
            else:
                self.__features_with_id[feature.id] = feature
        return feature

    def network_feature(self, feature: Feature) -> bool:
    #===================================================
        return self.__properties_store.network_feature(feature)

    def __add_proxied_features(self):
    #================================
        if self.__bottom_exported_layer is None:
            log.warning('No exported layer on which to add proxy features', type='proxy')
            return
        proxy_seqs = {}
        for proxy_definition in self.__properties_store.proxies:
            feature_model = proxy_definition['feature']
            if self.__feature_node_map.has_model(feature_model):
                log.warning('Proxied feature ignored already as already on the map', type='proxy', models=feature_model)
            else:
                for proxy_model in proxy_definition['proxies']:
                    if not self.__feature_node_map.has_model(proxy_model):
                        log.warning('Proxy missing from map', type='proxy', models=feature_model, proxy=proxy_model)
                    for feature in self.__feature_node_map.get_features(proxy_model):
                        proxy_seqs[feature.id] = proxy_seqs.get(feature.id, -1) + 1
                        self.__add_proxy_feature(feature, feature_model, proxy_seqs[feature.id])

    def __add_proxy_feature(self, feature: Feature, feature_model: str, proxy_seq: int):
    #================================================================================
        if 'Polygon' not in feature.geometry.geom_type:
            log.warning('Proxy feature must have a polygon shape', type='proxy', models=feature_model, feature=feature)
        elif self.__bottom_exported_layer is not None:
            self.__bottom_exported_layer.add_feature(
                self.new_feature(self.__bottom_exported_layer.id, proxy_dot(feature.geometry, proxy_seq), {   # type: ignore
                    'id': f'proxy_{proxy_seq}_on_{feature.id}',
                    'tile-layer': FEATURES_TILE_LAYER,
                    'models': feature_model,
                    'kind': 'proxy'
                })
            )

    def add_layer(self, layer: MapLayer):
    #====================================
        if layer.id in self.__layer_dict:
            raise KeyError('Duplicate layer id: {}'.format(layer.id))
        self.__layer_dict[layer.id] = layer
        if layer.exported:
            if self.__bottom_exported_layer is None:
                self.__bottom_exported_layer = layer
            self.__visible_layer_count += 1
            for feature in layer.features:
                if (feature.id is not None
                  and feature.properties.get('centreline', False)
                  and not feature.properties.get('excluded', False)):
                    feature.set_property('kind', 'centreline')
                    feature.set_property('type', 'line')
                    feature.set_property('tile-layer', PATHWAYS_TILE_LAYER)
                    self.__connection_set.add(feature.id,
                                              'centreline',
                                              feature.geojson_id,
                                              [])

    def get_layer(self, layer_id: str) -> Optional[MapLayer]:
    #========================================================
        return self.__layer_dict.get(layer_id)

    def add_source_layers(self, layer_number: int, source: 'MapSource'):
    #===================================================================
        for layer in source.layers:
            self.add_layer(layer)
            if layer.exported:
                layer.add_raster_layers(source.extent, source)
        # The first layer is used as the base map
        if layer_number == 0:
            if source.kind == 'details':
                raise ValueError('Details layer cannot be the base map')
            self.__extent = source.extent
            self.__centre = ((self.__extent[0] + self.__extent[2])/2,
                             (self.__extent[1] + self.__extent[3])/2)
            self.__area = source.map_area()
        elif (source.kind not in ['details', 'image', 'layer']
          and source.kind not in SOURCE_DETAIL_KINDS):
            raise ValueError('Can only have a single base map')

    def layer_metadata(self):
    #========================
        metadata = []
        for layer in self.__layer_dict.values():
            if layer.exported:
                map_layer = {
                    'id': layer.id,
                    'description': layer.description,
                    'detail-layer': layer.detail_layer,
                    'image-layers': [
                        {   'id': raster_layer.id,
                            'options': {
                                'max-zoom': raster_layer.max_zoom,
                                'min-zoom': raster_layer.min_zoom,
                                'background': raster_layer.background_layer,
                                'detail-layer': layer.detail_layer
                            }
                        } for raster_layer in layer.raster_layers
                    ]
                }
                if layer.min_zoom is not None:
                    map_layer['min-zoom'] = layer.min_zoom
                if layer.max_zoom is not None:
                    map_layer['max-zoom'] = layer.max_zoom
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
        log.info('Setting feature properties. Can take a while due to SciCrunch lookups...')
        for layer in self.__layer_dict.values():
            layer.set_feature_properties()

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

        log.info('Adding details...')
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
        new_feature = self.new_feature(layer_id, geometry, properties)
        new_feature.set_property('minzoom', minzoom)
        if properties.get('type') == 'nerve':
            new_feature.set_property('type', 'nerve-section')
            new_feature.set_property('nerveId', new_feature.geojson_id)  # Used in map viewer
            ## Need to link outline feature of nerve into paths through the nerve so it is highlighted
            ## when mouse over a path through the nerve
            new_feature.set_property('tile-layer', PATHWAYS_TILE_LAYER)
        detail_layer.add_feature(new_feature)
        return new_feature

    def __add_detail_features(self, layer, detail_layer, lowres_features):
    #=====================================================================
        extra_details = []
        for feature in lowres_features:
            hires_layer_id = feature.get_property('details')
            hires_layer = self.__layer_dict.get(hires_layer_id)
            if hires_layer is None:
                log.warning("Cannot find details layer '{}'".format(feature.get_property('details')))
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

            minzoom = feature.get_property('maxzoom') + 1
            if feature.get_property('type') != 'nerve':
                # Set the feature's geometry to that of the high-resolution outline
                feature.geometry = transform.transform_geometry(boundary_feature.geometry)
            else:                             # nerve
                feature.pop_property('maxzoom')

            if len(hires_layer.source.raster_sources):
                extent = transform.transform_extent(hires_layer.source.extent)
                layer.add_raster_layers(extent, hires_layer.source,
                                        id=f'{detail_layer.id}_{hires_layer.id}',
                                        min_zoom=minzoom, local_world_to_base=transform)

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
        return self.__properties_store.connectivity

    def __generate_connectivity(self):
    #=================================
        log.info('Generating connectivity...')
        # Route paths and set feature ids of path components
        self.__properties_store.generate_connectivity()
        self.__sckan_neuron_populations.generate_connectivity()

    def __setup_feature_search(self):
    #================================
        annotated_features = []
        for layer in self.__layer_dict.values():
            if layer.exported:
                annotated_features.extend([f for f in layer.features
                                              if f.models is not None
                                                and 'Polygon' in f.geom_type])      # type: ignore
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

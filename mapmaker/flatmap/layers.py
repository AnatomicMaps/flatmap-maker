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

class FeatureLayer(object):
    def __init__(self, id, source):
        self.__id = id
        self.__source = source
        self.__annotations = {}
        self.__description = 'Layer {}'.format(id)
        self.__features = []
        self.__features_with_id = {}
        self.__image_layers = []
        self.__detail_features = []
        self.__feature_types = []
#*        self.__ontology_data = self.options.ontology_data
        self.__outline_feature_id = None
        self.__queryable_nodes = False
        self.__selectable = True
        self.__selected = False
        self.__zoom = None

    @property
    def annotations(self):
        return self.__annotations

    @property
    def description(self):
        return self.__description

    @description.setter
    def description(self, value):
        self.__description = value

    @property
    def detail_features(self):
        return self.__detail_features

    @property
    def details_layer(self):
        return self.__details_layer

    @property
    def features_with_id(self):
        return self.__features_with_id

    @property
    def features(self):
        return self.__features

    @property
    def hidden(self):
        return self.__outline_feature_id is not None

    @property
    def id(self):
        return self.__id

    def set_id(self, id):
        self.__id = id

    @property
    def image_layers(self):
        return self.__image_layers

    @property
    def feature_types(self):
        return self.__feature_types

    @property
    def outline_feature_id(self):
        return self.__outline_feature_id

    @outline_feature_id.setter
    def outline_feature_id(self, value):
        self.__outline_feature_id = value

    @property
    def queryable_nodes(self):
        return self.__queryable_nodes

    @queryable_nodes.setter
    def queryable_nodes(self, value):
        self.__queryable_nodes = value

    @property
    def selected(self):
        return self.__selected

    @selected.setter
    def selected(self, value):
        self.__selected = value

    @property
    def selectable(self):
        return self.__selectable

    @selectable.setter
    def selectable(self, value):
        self.__selectable = value

    @property
    def source(self):
        return self.__source

    @property
    def zoom(self):
        return self.__zoom

    @zoom.setter
    def zoom(self, value):
        self.__zoom = value

    def add_feature(self, feature):
    #==============================
        self.__features.append(feature)
        if feature.has_property('details'):
            self.__detail_features.append(feature)
        id = feature.get_property('id')
        if id is not None:
            self.__features_with_id[id] = feature
        self.__feature_types.append({
            'type': feature.get_property('geometry')
        })

    def add_image_layer(self, id, slide_number, zoom, bounding_box=None, image_transform=None):
    #==========================================================================================
        self.__image_layers.append(ImageLayer(id, slide_number, zoom, bounding_box, image_transform))

    def extend_nerve_cuffs(self):
    #============================
        # Update feature properties from JSON properties file
        # and add polygon features for nerve cuffs
        nerve_polygons = []
        for feature in self.__features:
            ###
            ### Needs to be in a separate method (in Flatmap class??)
            ###self.mapmaker.update_properties(feature)   ### MAPMAKER...

            if (feature.get_property('type') == 'nerve'  ### but we don't know this because of deferred property setting...
            and feature.geom_type == 'LineString'):
                nerve_polygon_feature = self.__source.flatmap.new_feature_(
                    shapely.geometry.Polygon(feature.geometry.coords), feature.copy_properties())
                nerve_polygon_feature.del_property('models')
                nerve_polygon_feature.set_property('nerveId', feature.feature_id)  # Used in map viewer
                nerve_polygon_feature.set_property('tile-layer', 'pathways')
                nerve_polygons.append(nerve_polygon_feature)
        self.__features.extend(nerve_polygons)

#===============================================================================

class ImageLayer(object):
    def __init__(self, id, slide_number, zoom, bounding_box=None, image_transform=None):
        self.__bounding_box = bounding_box
        self.__id = '{}-image'.format(id)
        self.__slide_number = slide_number
        self.__image_transform = image_transform
        self.__zoom = zoom

    @property
    def bounding_box(self):
        return self.__bounding_box

    @property
    def id(self):
        return self.__id

    @property
    def image_transform(self):
        return self.__image_transform

    @property
    def slide_number(self):
        return self.__slide_number

    @property
    def zoom(self):
        return self.__zoom

#===============================================================================

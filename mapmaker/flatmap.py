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

import datetime
import json
import os
import subprocess

#===============================================================================

from mbtiles import MBTiles
from pathways import pathways_to_json
from styling import Style
from tilejson import tile_json

#===============================================================================

FLATMAP_VERSION  = 1.1

#===============================================================================

class MapLayer(object):
    def __init__(self, id, pathways=None):
        self.__annotations = {}
        self.__errors = []
        self.__pathways = pathways
        self.__map_features = []
#*        self.__ontology_data = self.settings.ontology_data


        self.__layer_id = 'layer-{}'.format(id)
        self.__description = 'Layer {}'.format(id)
        self.__models = ''
        self.__background_for = ''
        self.__selectable = True
        self.__selected = False
        self.__queryable_nodes = False
        self.__zoom = None

    @property
    def annotations(self):
        return self.__annotations

    @property
    def background_for(self):
        return self.__background_for

    @background_for.setter
    def background_for(self, value):
        self.__background_for = value

    @property
    def description(self):
        return self.__description

    @description.setter
    def description(self, value):
        self.__description = value

    @property
    def errors(self):
        return self.__errors

    @property
    def layer_id(self):
        return self.__layer_id

    @layer_id.setter
    def layer_id(self, value):
        self.__layer_id = value

    @property
    def map_features(self):
        return self.__map_features

    @property
    def models(self):
        return self.__models

    @models.setter
    def models(self, value):
        self.__models = value

    @property
    def queryable_nodes(self):
        return self.__queryable_nodes

    @queryable_nodes.setter
    def queryable_nodes(self, value):
        self.__queryable_nodes = value

    @property
    def resolved_pathways(self):
        return self.__pathways.resolved_pathways if self.__pathways is not None else None

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
    def slide_id(self):
        return self._slide.slide_id

    @property
    def zoom(self):
        return self.__zoom

    @zoom.setter
    def zoom(self, value):
        self.__zoom = value


    def error(self, msg):
    #====================
        self.__errors.append(msg)

#===============================================================================

class Flatmap(object):
    def __init__(self, id, source, creator, map_dir, zoom, bounds):
        self.__annotations = {}
        self.__bounds = bounds
        self.__centre = ((bounds[0]+bounds[2])/2, (bounds[1]+bounds[3])/2)
        self.__creator = creator
        self.__geojson_files = []
        self.__id = id
        self.__layers = []
        self.__layer_ids = []
        self.__map_dir = map_dir
        self.__mbtiles_file = os.path.join(map_dir, 'index.mbtiles') # The vector tiles' database
        self.__models = ''
        self.__pathways = []
        self.__source = source
        self.__tippe_inputs = []
        self.__upload_files = []
        self.__zoom = zoom

    def __len__(self):
        return len(self.__layers)

    @property
    def bounds(self):
        return self.__bounds

    @property
    def layer_ids(self):
        return self.__layer_ids

    @property
    def models(self):
        return self.__models

    def add_layer(self, layer):
    #==========================
        map_layer = {
            'id': layer.layer_id,
            'slide-id': layer.slide_id,
            'description': layer.description,
            'selectable': layer.selectable,
            'selected': layer.selected,
            'queryable-nodes': layer.queryable_nodes,
            'features': layer.map_features
        }
        if layer.background_for:
            map_layer['background_for'] = layer.background_for
        self.__layers.append(map_layer)
        self.__layer_ids.append(layer.layer_id)
        if layer.resolved_pathways is not None:
            self.__pathways.append(layer.resolved_pathways)
        if layer.models:
            self.__models = layer.models
        if layer.selectable:
            self.__annotations.update(layer.annotations)
            for (layer_name, filename) in layer.save().items():
                self.__geojson_files.append(filename)
                self.__tippe_inputs.append({
                    'file': filename,
                    'layer': layer_name,
                    'description': '{} -- {}'.format(layer.description, layer_name)
                })

    def make_vector_tiles(self):
    #===========================
        # Generate Mapbox vector tiles
        if len(self.__tippe_inputs) == 0:
            sys.exit('No selectable layers in Powerpoint...')
        subprocess.run(['tippecanoe', '--projection=EPSG:4326', '--force',
                        # No compression results in a smaller `mbtiles` file
                        # and is also required to serve tile directories
                        '--no-tile-compression',
                        '--buffer=100',
                        '--minimum-zoom={}'.format(self.__zoom[0]),
                        '--maximum-zoom={}'.format(self.__zoom[1]),
                        '--output={}'.format(self.__mbtiles_file),
                        ]
                        + list(["-L{}".format(json.dumps(input)) for input in self.__tippe_inputs])
                       )

        # `tippecanoe` uses the bounding box containing all features as the
        # map bounds, which is not the same as the extracted bounds, so update
        # the map's metadata
        tile_db = MBTiles(self.__mbtiles_file)
        tile_db.update_metadata(center=','.join([str(x) for x in self.__centre]),
                                bounds=','.join([str(x) for x in self.__bounds]))
        tile_db.execute("COMMIT")
        tile_db.close();
        self.add_upload_files(['index.mbtiles'])

    def save_map_json(self, has_image_layer):
    #========================================
        tile_db = MBTiles(self.__mbtiles_file)

        # Save path of the Powerpoint source
        tile_db.add_metadata(source=self.__source)    ## We don't always want this updated...
                                                   ## e.g. if re-running after tile generation
        # What the map models
        if self.__models:
            tile_db.add_metadata(describes=self.__models)
        # Save layer details in metadata
        tile_db.add_metadata(layers=json.dumps(self.__layers))
        # Save pathway details in metadata
        tile_db.add_metadata(pathways=pathways_to_json(self.__pathways))
        # Save annotations in metadata
        tile_db.add_metadata(annotations=json.dumps(self.__annotations))
        # Save command used to run mapmaker
        tile_db.add_metadata(created_by=self.__creator)
        # Save the maps creation time
        tile_db.add_metadata(created=datetime.datetime.utcnow().isoformat())
        # Commit updates to the database
        tile_db.execute("COMMIT")

#*        ## TODO: set ``layer.properties`` for annotations...
#*        ##update_RDF(args.map_base, args.map_id, source, annotations)
        map_index = {
            'id': self.__id,
            'min-zoom': self.__zoom[0],
            'max-zoom': self.__zoom[1],
            'bounds': self.__bounds,
            'version': FLATMAP_VERSION,
            'image_layer': has_image_layer
        }
        if self.__models:
            map_index['describes'] = self.__models
        # Create `index.json` for building a map in the viewer
        with open(os.path.join(self.__map_dir, 'index.json'), 'w') as output_file:
            json.dump(map_index, output_file)

        # Create style file
        metadata = tile_db.metadata()
        style_dict = Style.style(self.__layer_ids, metadata, self.__zoom)
        with open(os.path.join(self.__map_dir, 'style.json'), 'w') as output_file:
            json.dump(style_dict, output_file)

        # Create TileJSON file
        json_source = tile_json(self.__id, self.__zoom, self.__bounds)
        with open(os.path.join(self.__map_dir, 'tilejson.json'), 'w') as output_file:
            json.dump(json_source, output_file)

        tile_db.close();
        self.add_upload_files(['index.json', 'style.json', 'tilejson.json'])

    def add_upload_files(self, files):
    #=================================
        self.__upload_files.extend(files)

    def upload(self, host):
    #======================
        upload = ' '.join([ '{}/{}'.format(self.__id, f) for f in self.__upload_files ])
        cmd_stream = os.popen('tar -C {} -c -z {} | ssh {} "tar -C /flatmaps -x -z"'
                             .format(args.map_base, upload, host))

    def finalise(self, show_files=False):
    #====================================
        for filename in self.__geojson_files:
            if show_files:
                print(filename)
            else:
                os.remove(filename)

#===============================================================================

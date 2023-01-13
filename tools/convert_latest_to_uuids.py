#===============================================================================
#
#  Flatmap tools
#
#  Copyright (c) 2023 David Brooks
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

import argparse
import json
import logging
import os
import pathlib
import shutil
import tempfile

#===============================================================================

import git
import giturlparse

#===============================================================================
from flatmapknowledge import KnowledgeStore

from mapmaker.maker import Manifest
from mapmaker.output.mbtiles import MBTiles

#===============================================================================

def normalise_identifier(id):
    return ':'.join([(s[:-1].lstrip('0') + s[-1])
                        for s in id.split(':')])

#===============================================================================

class Flatmap:
    def __init__(self, flatmap_dir):
        index_file = os.path.join(flatmap_dir, 'index.json')
        mbtiles = os.path.join(flatmap_dir, 'index.mbtiles')
        if (not os.path.isdir(flatmap_dir)
         or not os.path.exists(index_file)
         or not os.path.exists(mbtiles)):
            raise TypeError(f'Invalid or missing flatmap directory: {flatmap_dir}')

        with open(index_file) as fp:
            self.__index = json.loads(fp.read())
        version = self.__index.get('version', 1.0)
        if version < 1.3:
            raise TypeError(f'Flatmap version is too old: {flatmap_dir}')

        tile_db = MBTiles(mbtiles)
        metadata = tile_db.metadata('metadata')
        tile_db.close()
        if (('id' not in metadata or flatmap_dir.name != metadata['id'])
         and ('uuid' not in metadata or flatmap_dir.name != metadata['uuid'].split(':')[-1])):
            raise TypeError(f'Flatmap id mismatch: {flatmap_dir}')

        flatmap = {
            'id': metadata['id'],
            'source': metadata['source'],
            'version': version
        }
        if 'created' in metadata:
            flatmap['created'] = metadata['created']
        if 'taxon' in metadata:
            flatmap['taxon'] = normalise_identifier(metadata['taxon'])
            flatmap['describes'] = metadata['describes'] if 'describes' in metadata else flatmap['taxon']
        elif 'describes' in metadata:
            flatmap['taxon'] = normalise_identifier(metadata['describes'])
            flatmap['describes'] = flatmap['taxon']
        if 'biological-sex' in metadata:
            flatmap['biologicalSex'] = metadata['biological-sex']
        if 'uuid' in metadata:
            flatmap['uuid'] = metadata['uuid']
        if 'name' in metadata:
            flatmap['name'] = metadata['name']
        self.__flatmap = flatmap

    def __getitem__(self, key):
        return self.__flatmap[key]

    def __setitem__(self, key, value):
        self.__flatmap[key] = value

    def __delitem__(self, key):
        del self.__flatmap[key]

    def __contains__(self, key):
        return key in self.__flatmap

    def __len__(self):
        return len(self.__flatmap)

    def __repr__(self):
        return repr(self.__flatmap)

    @property
    def index(self):
        return self.__index

#===============================================================================

def latest_flatmaps(flatmap_root):
#=================================
    flatmaps_by_dir = {}
    root_path = pathlib.Path(flatmap_root).absolute()
    if root_path.is_dir():
        for flatmap_dir in root_path.iterdir():
            try:
                flatmaps_by_dir[str(flatmap_dir)] = Flatmap(flatmap_dir)
            except TypeError as e:
                logging.error(str(e))
                continue
    maps_by_taxon_sex = {}
    for flatmap_dir, flatmap in flatmaps_by_dir.items():
        if ((created := flatmap.get('created')) is not None
        and (taxon := flatmap.get('taxon', flatmap.get('describes'))) is not None):
            map_key = (taxon, flatmap.get('biologicalSex', ''))
            if (map_key not in maps_by_taxon_sex
             or created > maps_by_taxon_sex[map_key][0]):
                maps_by_taxon_sex[map_key] = (created, flatmap_dir, flatmap)

    return { flatmap_dir: flatmap for _, flatmap_dir, flatmap in maps_by_taxon_sex.values() }

#===============================================================================

class FlatmapSource:
    def __init__(self, flatmap):
        map_source = flatmap['source']
        git_url = giturlparse.parse(map_source)
        if not git_url.domain.endswith('physiomeproject.org'):
            raise TypeError('Only `physiomeproject.org` sources are currently supported')
        parts = git_url.groups_path.split('/')
        repo_path = f'{git_url.protocol}://{git_url.host}{git_url.port}/{git_url.owner}/{parts[0]}'
        working_dir = tempfile.TemporaryDirectory()
        repo = git.Repo.clone_from(repo_path, working_dir)
        repo.head.reference = repo.commit(parts[-1])
        repo.head.reset(index=True, working_tree=True)
        self.__manifest = Manifest(f'{working_dir}/{git_url.repo}')

    @property
    def manifest(self):
        return self.__manifest

#===============================================================================

class FlatmapConvertor:
    def __init__(self, output_root, final_root=None):
        self.__output_path = pathlib.Path(output_root).absolute()
        self.__final_root = final_root if final_root is not None else str(self.__output_path)
        self.__store = KnowledgeStore(output_root, create=False)

    def convert(self, flatmap_dir, manifest):
        output_dir = self.__output_path / manifest.uuid
        if output_dir.exists():
            return None
        shutil.copytree(flatmap_dir, output_dir)

        with open(output_dir / 'index.json') as fp:
            index = json.loads(fp.read())
        index['id'] = manifest.id
        index['uuid'] = manifest.uuid
        index['taxon'] = manifest.models
        index['describes'] = self.__store.entity_knowledge(manifest.models)['label']
        if index['taxon'] == 'NCBITaxon:9606' and 'biologicalSex' not in index:
            index['biologicalSex'] = 'PATO:0000384'
        if 'image_layer' in index:
            index['image-layers'] = index.pop('image_layer')
        index['git-status'] = manifest.git_status
        index['style'] = 'flatmap'
        with open(output_dir / 'index.json', 'w') as fp:
            fp.write(json.dumps(index))

        mbtiles_file = output_dir / 'index.mbtiles'
        tile_db = MBTiles(mbtiles_file)
        metadata = json.loads(str(tile_db.metadata(name='metadata')))
        metadata.pop('name', None)
        metadata['id'] = index['id']
        metadata['uuid'] = index['uuid']
        metadata['taxon'] = index['taxon']
        metadata['describes'] = index['describes']
        metadata['git-status'] = index['git-status']
        if 'biologicalSex' in index:
            metadata['biologicalSex'] = index['biologicalSex']
        tile_db.execute("delete from metadata where name='id'")
        tile_db.execute("delete from metadata where name='describes'")
        tile_db.add_metadata(metadata=json.dumps(metadata))
        tile_db.add_metadata(name=str(mbtiles_file))
        tile_db.add_metadata(description=str(mbtiles_file))
        tile_db.close()

        if self.__store.db is not None:
            self.__store.db.execute('begin')
            self.__store.db.execute('replace into flatmaps(id, models, created) values (?, ?, ?)',
                                        (manifest.uuid, manifest.models, index['created']))
            self.__store.db.commit()

        return metadata['uuid']

#===============================================================================

def main():
    import sys

    parser = argparse.ArgumentParser(description='Upgrade most recent maps for each species on a flatmap server to use GUIDs.')
    parser.add_argument('--id', metavar='ID', help='Only process this map (and only if it is the latest for a species)')
    parser.add_argument('--final-dest', metavar='FINAL_DESTINATION_FLATMAP_ROOT', help='Full path to flatmap root where destination maps will be placed')
    parser.add_argument('source_flatmaps', metavar='SOURCE_FLATMAP_ROOT')
    parser.add_argument('dest_flatmaps', metavar='DESTINATION_FLATMAP_ROOT')
    args = parser.parse_args()

    if args.dest_flatmaps == args.source_flatmaps:
        sys.exit('Source and destination root directories must be different')
    if args.final_dest is not None and not args.final_dest.startswith('/'):
        sys.exit('Final destination path must start with `/`')

    conversion_table = {}
    convertor = FlatmapConvertor(args.dest_flatmaps, args.final_dest)
    for flatmap_dir, flatmap in latest_flatmaps(args.source_flatmaps).items():
        taxon = flatmap['taxon']
        if 'uuid' in flatmap:
            logging.info(f'Skipped {taxon} ({flatmap_dir}) as already uses GUID')
            continue
        elif args.id is not None and args.id != flatmap['id']:
            continue
        try:
            flatmap_source = FlatmapSource(flatmap)
        except TypeError as e:
            logging.error(str(e))
            continue
        guid = convertor.convert(flatmap_dir, flatmap_source.manifest)
        if guid is not None:
            conversion_table[taxon] = guid
            logging.info(f'Saved {taxon} ({flatmap_dir}) as {guid}')
        else:
            logging.info(f'Skipped {taxon} ({flatmap_dir}) as GUID already exists')

    print(json.dumps(conversion_table, indent=4))

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================

'''


id|1220ab6b172448ccf9dd8c4d748447248d3185b25123dd5b4700d33c04d80011   ## delete
describes|NCBITaxon:9823   ### delete


name|whole-pig             ### replace
set both "description" and "name" to full path to new index.mbtiles

/home/ubuntu/services/prod-flatmap-server-v2/flatmaps/1220ab6b172448ccf9dd8c4d748447248d3185b25123dd5b4700d33c04d80011/index.mbtiles
/Users/dbro078/Flatmaps/map-server/flatmaps/0434e45b-8830-534a-9abc-f871f385f14c/index.mbtiles


Copy flatmap_dir contents to new flatmap_root/uuid directory then modify index.json as above


Next update metadata in index.mbtiles in new directory


        metadata = self.__flatmap.metadata
        metadata['settings'] = self.__options
        metadata.update(self.__git_status)
        tile_db.add_metadata(metadata=json.dumps(metadata))




{
    "id": "1220ab6b172448ccf9dd8c4d748447248d3185b25123dd5b4700d33c04d80011",  ## --> manifest.id
                                                                               ## uuid = manifest.uuid
    "source": "https://models.physiomeproject.org/workspace/6eb/rawfile/e8341d8301e2def368343de35d2465f202c7780a/manifest.json",
    "min-zoom": 2,
    "max-zoom": 10,
    "bounds": [-19.403896699557297, -14.398403706782805, 19.403896699557297, 14.398403706782805],
    "version": 1.3,
    "image_layer": true,            ## key -> image-layers
    "describes": "NCBITaxon:9823"   ## key -> taxon
                                    ## lookup describes
                                    ## set biologicalSex = "PATO:0000384" if taxon == "NCBITaxon:9606"
                                    ## "git-status" = manifest.git_status
                                    ## "style" = "flatmap"
}



description|/home/ubuntu/services/prod-flatmap-server-v2/flatmaps/1220ab6b172448ccf9dd8c4d748447248d3185b25123dd5b4700d33c04d80011/index.mbtiles

metadata|{"id": "1220ab6b172448ccf9dd8c4d748447248d3185b25123dd5b4700d33c04d80011", "name": "whole-pig", "creator": "mapmaker 1.3.0b7", "source": "https://models.physiomeproject.org/workspace/6eb/rawfile/e8341d8301e2def368343de35d2465f202c7780a/manifest.json", "version": 1.3, "describes": "NCBITaxon:9823", "created": "2021-12-10T09:35:00.948552"}
{
    "id": "1220ab6b172448ccf9dd8c4d748447248d3185b25123dd5b4700d33c04d80011",
    "name": "whole-pig",
    "creator": "mapmaker 1.3.0b7",
    "source": "https://models.physiomeproject.org/workspace/6eb/rawfile/e8341d8301e2def368343de35d2465f202c7780a/manifest.json",
    "version": 1.3,
    "describes": "NCBITaxon:9823",
    "created": "2021-12-10T09:35:00.948552"
}



{
    "id": "human-flatmap_male",
    "uuid": "0434e45b-8830-534a-9abc-f871f385f14c",
    "source": "https://github.com/AnatomicMaps/human-flatmap/blob/5564310c9763be1dd7cab6867ce3499d496001f1/male.manifest.json",
    "min-zoom": 2,
    "max-zoom": 10,
    "bounds": [-15.732891461948963, -15.656807270737906, 15.732891461948963, 15.656807270737906],
    "version": 1.5,
    "image-layers": true,
    "taxon": "NCBITaxon:9606",
    "biologicalSex": "PATO:0000384",
    "style": "flatmap",
    "git-status":
    {
        "sha": "5564310c9763be1dd7cab6867ce3499d496001f1",
        "remotes":
        {
            "origin": "https://github.com/AnatomicMaps/human-flatmap.git"
        }
    }
}



metadata|{
    "id": "human-flatmap_male",
    "uuid": "0434e45b-8830-534a-9abc-f871f385f14c",
    "name": "human-flatmap_male",
    "creator": "mapmaker 1.5.5-b.1",
    "source": "https://github.com/AnatomicMaps/human-flatmap/blob/5564310c9763be1dd7cab6867ce3499d496001f1/male.manifest.json",
    "version": 1.5,
    "taxon": "NCBITaxon:9606",
    "biological-sex": "PATO:0000384",
    "describes": "Homo sapiens",
    "created": "2022-12-08T22:10:43.606491",
    "settings":
    {
        "logFile": null,
        "showDeprecated": false,
        "silent": false,
        "verbose": false,
        "clean": true,
        "backgroundTiles": true,
        "authoring": false,
        "debug": true,
        "onlyNetworks": false,
        "saveDrawML": false,
        "saveGeoJSON": false,
        "showTippe": false,
        "initialZoom": 4,
        "maxZoom": 10,
        "minZoom": 2,
        "cleanConnectivity": false,
        "singleFile": null,
        "output": "/Users/dbro078/Flatmaps/map-server/flatmaps",
        "source": "../published/sources/human/male.manifest.json"
    },
    "git-status":
    {
        "sha": "5564310c9763be1dd7cab6867ce3499d496001f1",
        "remotes":
        {
            "origin": "https://github.com/AnatomicMaps/human-flatmap.git"
        }
    }
}

'''
















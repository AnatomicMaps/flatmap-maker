#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2021  David Brooks
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

import pickle

#===============================================================================

class Track(object):
    def __init__(self, id, bezier_segments, regions=None):
        self.__id = id
        self.__bezier_segments = bezier_segments
        self.__regions = regions

#===============================================================================

class Region(object):
    def __init__(self, id, geometry):
        self.__id = id
        self.__geometry = geometry

#===============================================================================

class Segment(object):
    def __init__(self, start_regions, end_regions, track):
        self.__start_regions = start_regions
        self.__end_regions = end_regions
        self.__track = track

    def __str__(self):
        return '{} --> {} via {}'.format(self.__start_regions, self.__end_regions, self.__track)

#===============================================================================

class PathRouter(object):
    def __init__(self, regions, tracks):
        self.__regions = regions
        self.__tracks = tracks
        print('Regions:', list(regions.keys()))
        print('Tracks:', list(tracks.keys()))

    def find_route(self, segments):
        print('Routing:\n  {}'.format('\n  '.join([str(s) for s in segments])))

#===============================================================================

PICKLED_DATA = 'autoroute.pickle'

def save_data(regions, tracks, segments):
#========================================
    data = {
        'regions': {f.feature_id: Region(f.feature_id, f.geometry)
                            for f in regions},
        'tracks': {f.feature_id: Track(f.feature_id, f.get_property('bezier-segments', []))
                            for f in tracks},
        'segments': [ Segment(*s) for s in segments ]
    }
    print('Saving', data)
    with open(PICKLED_DATA, 'wb') as fp:
        pickle.dump(data, fp)

def load_data():
#===============
    with open(PICKLED_DATA, 'rb') as fp:
        data = pickle.load(fp)
    return data

#===============================================================================

if __name__ == '__main__':
    data = load_data()

    pr = PathRouter(data['regions'], data['tracks'])
    pr.find_route(data['segments'])

#===============================================================================

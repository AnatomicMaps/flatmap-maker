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

import os
import sqlite3

#===============================================================================

import requests

#===============================================================================

#ILX_ENDPOINT = 'http://uri.interlex.org/base/ilx_{}.json'
VOCAB_ENDPOINT = 'https://scigraph.olympiangods.org/scigraph/vocabulary/id/{}.json'

#===============================================================================

class LabelData(object):
    def __init__(self, database):
        new_db = not os.path.exists(database)
        self._db = sqlite3.connect(database)
        self._cursor = self._db.cursor()
        if new_db:
            self._cursor.execute('CREATE TABLE labels (entity text, label text)')
            self._db.commit()

    def close(self):
        self._db.close()

    def set_label(self, entity, label):
        self._cursor.execute('REPLACE INTO labels(entity, label) VALUES (?, ?)', (entity, label))
        self._db.commit()

    def get_label(self, entity):
        self._cursor.execute('SELECT label FROM labels WHERE entity=?', (entity,))
        row = self._cursor.fetchone()
        if row is not None:
            return row[0]
        label = entity
        if not entity.startswith('ILX:'):
            try:
                response = requests.get(VOCAB_ENDPOINT.format(entity))
                if response:
                    l = response.json().get('labels', [entity])[0]
                    label = l[0].upper() + l[1:]
                    self.set_label(entity, label)
            except:
                print("Couldn't access", VOCAB_ENDPOINT.format(entity))
        return label

#===============================================================================

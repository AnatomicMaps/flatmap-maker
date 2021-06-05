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

import io
import os
import sqlite3

#===============================================================================

import cv2
import numpy as np

import mbutil as mb

#===============================================================================

class ExtractionError(Exception):
    pass

#===============================================================================

class MBTiles(object):
    def __init__(self, filepath, create=False, force=False, silent=False):
        self._silent = silent
        if force and os.path.exists(filepath):
            os.remove(filepath)
        self._connnection = mb.mbtiles_connect(filepath, self._silent)
        self._cursor = self._connnection.cursor()
        mb.optimize_connection(self._cursor)
        if create:
            mb.mbtiles_setup(self._cursor)

    def close(self, compress=False):
        if compress:
            mb.compression_prepare(self._cursor, self._silent)
            mb.compression_do(self._cursor, self._connnection, 256, self._silent)
            mb.compression_finalize(self._cursor)
        mb.optimize_database(self._connnection, self._silent)

    def execute(self, sql):
        return self._cursor.execute(sql)

    def add_metadata(self, **metadata):
        for name, value in metadata.items():
            self._cursor.execute('replace into metadata(name, value) values (?, ?);',
                                                                            (name, value))

    def metadata(self, name=None):
        if name is not None:
            return self._cursor.execute('select value from metadata where name=?;', (name, )).fetchone()[0]
        else:
            return dict(self._connnection.execute('select name, value from metadata;').fetchall())

    def get_tile(self, zoom, x, y):
        rows = self._cursor.execute("""select tile_data from tiles
                                          where zoom_level=? and tile_column=? and tile_row=?;""",
                                                          (zoom,             x,             mb.flip_y(zoom, y)))
        data = rows.fetchone()
        if not data: raise ExtractionError()
        return cv2.imdecode(np.frombuffer(data[0], 'B'), cv2.IMREAD_UNCHANGED)

    def save_tile_as_png(self, zoom, x, y, image):
        output = cv2.imencode('.png', image)[1]
        self._cursor.execute("""insert into tiles (zoom_level, tile_column, tile_row, tile_data)
                                           values (?, ?, ?, ?);""",
                                                  (zoom, x, mb.flip_y(zoom, y), sqlite3.Binary(output))
                            )

#===============================================================================

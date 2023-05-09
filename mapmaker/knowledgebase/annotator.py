#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2023  David Brooks
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

import json
from pathlib import Path
import sqlite3

#===============================================================================

from mapmaker.settings import settings
from mapmaker.utils import log

#===============================================================================

class AnnotatorDatabase:
    def __init__(self, flatmap_dir):
        self.__db = None
        db_name = (Path(flatmap_dir) / '..' / 'annotation.db').resolve()
        if db_name.exists():
            self.__db = sqlite3.connect(db_name)
        elif settings.get('exportNeurons') is not None:
            log.warning(f'Missing annotator database: {db_name}')

    def get_derivation(self, feature_id: str, http_only=True) -> list[str]:
    #======================================================================
        result = []
        if self.__db is not None:
            row = self.__db.execute('''select value from annotations as a
                                        where created=(select max(created) from annotations
                                            where feature=? and property='prov:wasDerivedFrom')
                                        and a.property='prov:wasDerivedFrom' ''',
                                    (feature_id,)).fetchone()
            if row:
                result = json.loads(row[0])
        return result

#===============================================================================

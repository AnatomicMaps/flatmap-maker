#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019-21  David Brooks
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

from pathlib import Path
import sqlite3

#===============================================================================

from flatmapknowledge import KnowledgeStore

#===============================================================================

from mapmaker.settings import settings

#===============================================================================

def connectivity_models():
    return settings['KNOWLEDGE_STORE'].connectivity_models()

def get_label(entity):
    return get_knowledge(entity).get('label', entity)

def get_knowledge(entity):
    return settings['KNOWLEDGE_STORE'].entity_knowledge(entity)

#===============================================================================

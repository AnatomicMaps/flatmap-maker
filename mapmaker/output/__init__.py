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

# These properties of a feature are passed to the viewer along with ``bounds``,
# ``geometry``, ``layer` and ``markerPosition``, which are added when the feature
# is saved as GeoJSON.

EXPORTED_FEATURE_PROPERTIES = [
    'centreline',
    'class',
    'colour',
    'error',
    'featureId',
    'group',
    'hyperlink',
    'id',
    'invisible',
    'kind',
    'label',
    'labelled',
    'maxzoom',
    'minzoom',
    'models',
    'name',
    'nerveId',
    'node',
    'nodeId',
    'opacity',
    'scale',
    'sckan',
    'source',
    'stroke-width',
    'tile-layer',
    'type',
    'warning',
]

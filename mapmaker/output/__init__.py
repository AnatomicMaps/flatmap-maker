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

# These properties of a feature are passed to the viewer along with ``bounds``,
# ``geometry``, ``layer` and ``markerPosition``, which are added when the feature
# is saved as GeoJSON.

EXPORTED_FEATURE_PROPERTIES = [
    'cd-class',         # str
    'associated-details', # Optional[str|list[str]]      Identifiers of detailed layers associated with the feature
    'centreline',       # bool
    'children',         # list[int]
    'class',
    'colour',           # str
    'description',      # str
    'details-layer',    # str       The identifier of the layer with details about the feature
    'error',
    'fc-class',
    'fc-kind',
    'featureId',        # int
    'group',
    'hyperlink',        # Optional[str]
    'hyperlinks',       # Optional[list[dict[str, str]]]    # id, url
    'id',               # Optional[str]
    'invisible',        # bool
    'kind',
    'label',
    'labelled',         # bool
    'maxzoom',          # int
    'minzoom',          # int
    'models',
    'name',
    'nerves',           # Optional[list[str]]
    'nerveId',
    'node',             # bool
    'nodeId',
    'opacity',          # float
    'parents',          # list[int]
    'scale',
    'sckan',
    'source',
    'stroke',           # str
    'stroke-width',     # float
    'path-ids',         # list[str]
    'taxons',           # list[str]
    'tile-layer',
    'type',
    'warning',
    'completeness',
    'missing-nodes',
    'alert',
    'biological-sex',
    'anatomical-nodes'  # list[[str, list[str]]]
]

#===============================================================================

ENCODED_FEATURE_PROPERTIES = [
    'hyperlinks',       # Optional[list[dict[str, str]]]    # id, url
    'associated-details',   # Optional[str|list[str]]
]

#===============================================================================

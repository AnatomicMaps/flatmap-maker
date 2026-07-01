#===============================================================================
#
#  CellDL and bondgraph tools
#
#  Copyright (c) 2020 - 2026 David Brooks
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

# Exports
from .namespace import *
from .rdfgraph import *

#===============================================================================

def literal_as_string(literal: Literal|None) -> str|None:
    return literal.value if literal is not None else None

def uri_fragment(uri: str|NamedNode) -> str:
    if isNamedNode(uri):
        uri_as_string = uri.value       # pyright: ignore[reportAttributeAccessIssue]
    else:
        uri_as_string: str = uri        # pyright: ignore[reportAssignmentType]
    if '#' in uri_as_string:
        return uri_as_string.rsplit('#')[-1]
    else:
        return uri_as_string.rsplit('/')[-1]

#===============================================================================

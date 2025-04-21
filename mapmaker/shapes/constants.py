#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2018 - 2025  David Brooks
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

EPSILON = 1e-6
MAX_PARALLEL_SKEW = 0.001

#===============================================================================

# The ratio of the difference between the lengths of a candidate arrow's point
# edges and their sum must be less than 0.001

ARROW_POINT_EPSILON = 1e-3

# The ratio of the actual overlap to the combined length of parallel edges needs
# to be at least 0.6 for them to be candidates for merging into a line

LINE_OVERLAP_RATIO = 0.6

# The combined length of parallel edges needs to be at least 1.5 times the distance
# between them for them to be candidates for merging

MIN_LINE_ASPECT_RATIO = 1.5     #

# SVG pixel space -- these values are based on the CVS bondgraph diagram

MAX_LINE_WIDTH = 20             # Close together parallel edges a polygons are converted to lines

MAX_TEXT_VERTICAL_OFFSET = 3    # Between cluster baseline and baselines of text in the cluster
TEXT_BASELINE_OFFSET = -14.5    # From vertical centre of a component

# Text shapes need at least 80% containment in their parent
MIN_TEXT_INSIDE = 0.8

#===============================================================================

# Scaling factors for styling components and connections in map viewers

COMPONENT_BORDER_WIDTH = 2
CONNECTION_STROKE_WIDTH = 2

#===============================================================================

SHAPE_ERROR_COLOUR = 'yellow'
SHAPE_ERROR_BORDER = 'red'

#===============================================================================

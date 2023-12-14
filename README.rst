.. highlight:: sh

========
Mapmaker
========

Overview
--------

Mapmaker is a Python application for generating `Mapbox <https://www.mapbox.com/>`_ compatible tilesets from
a range of sources, currently Powerpoint slides, SVG diagrams, and segmented image files from MBF Biosciences.

Documentation
-------------

* https://flatmap-maker.readthedocs.io/en/latest/

Installation
------------

We recommend that ``mapmaker`` is run in a Conda environment on a Linux or macOS system. This includes
`Windows Subsystem for Linux <https://learn.microsoft.com/en-us/windows/wsl/install>`_ (WSL) for Microsoft
Windows systems.

Prerequisites
~~~~~~~~~~~~~
Install a ``miniforge`` environment as descibed `here <https://github.com/conda-forge/miniforge>`_.

macOS
^^^^^

Apple macOS users may first have to install the ``XCode command line tools``. Check if the command line tools are installed by running::

    $  xcode-select -p

and if they are not, install them by running::

    $ xcode-select --install


Installation
~~~~~~~~~~~~

*   At a CLI prompt, and in a suitable directory,
    `download the latest release <https://github.com/AnatomicMaps/flatmap-maker/archive/refs/tags/v1.7.0.tar.gz>`_
    in ``tar.gz`` format and extract it, renaming the top-level directory in the archive to ``mapmaker``::

        $ curl -L https://github.com/AnatomicMaps/flatmap-maker/archive/refs/tags/v1.7.0.tar.gz \
        | tar xz -s /v1.7.0.tar.gz/mapmaker/


Setup the environment
^^^^^^^^^^^^^^^^^^^^^

*   Change into the ``mapmaker`` directory and install dependencies using Conda::

        $ conda env create -f envs/mapmaker.yaml


Running
-------

*   Activate ``mapmaker``'s Conda environment::

        $ conda activate mapmaker


*   From the ``mapmaker`` directory use ``python`` to execute ``runmaker.py``::

        $ python runmaker.py ARGUMENTS


*   `SciCrunch <https://scicrunch.org/>`_ is used to lookup attributes (e.g. labels) of anatomical entities. In order
    to use these services a valid SciCrunch API key must be provided as the ``SCICRUNCH_API_KEY`` environment variable.
    (Keys are obtained by registering as a SciCrunch user).


Updating
--------

*   Download and extract the archive of the latest release as above, overwriting the existing
    ``mapmaker`` installation directory.
*   With the Conda environment active, and within the ``mapmaker`` directory::

        $  conda env update -f envs/mapmaker.yaml


Command line help
-----------------

::

    $ python runmaker.py --help

.. code-block:: text

    usage: mapmaker [-h] [-v]
                    [--log LOG_FILE] [--show-deprecated] [--silent] [--verbose]
                    [--clean] [--clean-connectivity] [--background-tiles] [--id ID]
                    [--ignore-git] [--ignore-sckan] [--invalid-neurons] [--publish SPARC_DATASET]
                    [--sckan-version {production,staging}]
                    [--authoring] [--debug] [--only-networks] [--save-drawml] [--save-geojson] [--tippecanoe]
                    [--initial-zoom N] [--max-zoom N] [--min-zoom N]
                    [--export-identifiers EXPORT_FILE] [--export-neurons EXPORT_FILE] [--export-svg EXPORT_FILE]
                    [--single-file {celldl,svg}]
                    --output OUTPUT --source SOURCE

    Generate a flatmap from its source manifest.

    options:
      -h, --help            show this help message and exit
      -v, --version         show program's version number and exit

    Logging:
      --log LOG_FILE        Append messages to a log file
      --show-deprecated     Issue a warning for deprecated markup properties
      --silent              Suppress all messages to screen
      --verbose             Show progress bars

    Map generation:
      --clean               Remove all files from generated map's directory before
                            generating the new map
      --clean-connectivity  Refresh local connectivity knowledge from SciCrunch
      --background-tiles    Generate image tiles of map's layers (may take a
                            while...)
      --id ID               Set explicit ID for flatmap, overriding manifest
      --ignore-git          Don't check that sources are committed into git
      --ignore-sckan        Don't check if functional connectivity neurons are known
                            in SCKAN. Sets `--invalid-neurons` option
      --invalid-neurons     Include functional connectivity neurons that aren't known
                            in SCKAN
      --publish SPARC_DATASET
                            Create a SPARC Dataset containing the map's sources and the generated map
      --sckan-version {production,staging}
                            Overide version of SCKAN specified by map's manifest

    Diagnostics:
      --authoring           For use when checking a new map: highlight incomplete
                            features; show centreline network; no image tiles; no
                            neuron paths; etc
      --debug               See `log.debug()` messages in log
      --only-networks       Only output features that are part of a centreline
                            network
      --save-drawml         Save a slide's DrawML for debugging
      --save-geojson        Save GeoJSON files for each layer
      --tippecanoe          Show command used to run Tippecanoe

    Zoom level:
      --initial-zoom N      Initial zoom level (defaults to 4)
      --max-zoom N          Maximum zoom level (defaults to 10)
      --min-zoom N          Minimum zoom level (defaults to 2)

    Miscellaneous:
      --export-identifiers EXPORT_FILE
                            Export identifiers and anatomical terms of features as JSON
      --export-neurons EXPORT_FILE
                            Export details of functional connectivity neurons as JSON
      --export-svg EXPORT_FILE
                            Export Powerpoint sources as SVG
      --single-file {celldl,svg}
                            Source is a single file of the designated type, not a
                            flatmap manifest

    Required arguments:
      --output OUTPUT       Base directory for generated flatmaps
      --source SOURCE       URL or path of a flatmap manifest


Manifest files
--------------

The sources of a flatmap are specified using a JSON file, usually called ``manifest.json``. See :ref:`manifest-files` for details.

Anatomical map file
-------------------

TODO...

Properties file
---------------

TODO...


Shape markup
------------

TODO...


Integration
-----------

TODO...

*   Python wheel available.


Development
-----------

``mapmaker`` uses `poetry <https://python-poetry.org/docs/#installation>`_ for dependency management and packaging.
To create a development environment::

    $ git clone https://github.com/AnatomicMaps/flatmap-maker.git mapmaker
    $ cd mapmaker
    $ poetry install


Building documentation
~~~~~~~~~~~~~~~~~~~~~~

In development mode, and within the Python virtual environment::

    $ cd docs
    $ make html


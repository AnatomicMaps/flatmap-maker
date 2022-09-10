Installation and running on an M1 Mac
=====================================

Prerequisites
-------------

* XCode command line tools::

    $ xcode-select --install

* Miniforge, including latest Python 3::

    $ curl -L -O  "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-arm64.sh"
    $ sh Miniforge3-MacOSX-arm64.sh

Reply ``yes`` when asked to initialise Miniforge3. Then create a new shell (e.g. logout and back in again).

Installation
------------

* Mapmaker::

    $ git clone https://github.com/AnatomicMaps/flatmap-maker.git mapmaker
    $ cd mapmaker
    $ conda env create -f conda/M1Mac.yaml

Running
-------

* Activate ``mapmaker``'s environment::

    $ conda activate mapmaker

* Run::

    $ python runmaker.py ARGUMENTS


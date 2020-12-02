"""A setuptools based setup module.
See:
https://packaging.python.org/guides/distributing-packages-using-setuptools/
https://github.com/pypa/sampleproject
Modified by Madoshakalaka@Github (dependency links added)
"""

# Always prefer setuptools over distutils
from setuptools import setup, find_packages
from os import path

# Arguments marked as "Required" below must be included for upload to PyPI.
# Fields marked as "Optional" may be commented out.

setup(
    version="0.7.0",  # Required
    name="mapmaker",
    description="Convert Powerpoint slides to Mapbox tiles",
    url="https://github.com/dbrnz/flatmap-maker",
    author="David Brooks",
    author_email="d.brooks@auckland.ac.nz",
    classifiers=[
        # How mature is this project? Common values are
        #   3 - Alpha
        #   4 - Beta
        #   5 - Production/Stable
        "Development Status :: 4 - Beta",
        # Indicate who your project is intended for
        "Intended Audience :: Developers",
        "Topic :: Software Development",
        # Pick your license as you wish
        "License :: OSI Approved :: Apache Software License",
        # Specify the Python versions you support here. In particular, ensure
        # that you indicate whether you support Python 2, Python 3 or both.
        # These classifiers are *not* checked by 'pip install'. See instead
        # 'python_requires' below.
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
    ],
    # This field adds keywords for your project which will appear on the
    # project page. What does your project relate to?
    #
    # Note that this is a string of words separated by whitespace, not a list.
    #keywords="TODO...",  # Optional
    #
    packages=[
        "mapmaker",
        "mapmaker.flatmap",
        "mapmaker.geometry",
        "mapmaker.knowledgebase",
        "mapmaker.output",
        "mapmaker.properties",
        "mapmaker.sources",
        "mapmaker.sources.mbfbioscience",
        "mapmaker.sources.powerpoint",
        "mapmaker.sources.svg",
        "mapmaker.utils",
    ],
    python_requires=">=3.7, <4",
    install_requires=[
        "alembic==1.4.3; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3'",
        "beziers==0.1.0",
        "certifi==2020.11.8",
        "chardet==3.0.4",
        "click==7.1.2; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3, 3.4'",
        "configargparse==1.2.3",
        "cssselect2==0.4.1; python_version >= '3.6'",
        "et-xmlfile==1.0.1",
        "idna==2.10; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3'",
        "isodate==0.6.0",
        "jdcal==1.4.1",
        "lxml==4.6.2",
        "mako==1.1.3; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3'",
        "markupsafe==1.1.1; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3'",
        "mbutil==0.3.0",
        "mercantile==1.1.6",
        "numpy==1.19.4",
        "opencv-python-headless==4.4.0.46",
        "openpyxl==3.0.5",
        "pillow==8.0.1; python_version >= '3.6'",
        "pyclipper==1.2.0",
        "pymupdf==1.18.4",
        "pyparsing==2.4.7",
        "pyproj==3.0.0.post1",
        "python-dateutil==2.8.1; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3'",
        "python-editor==1.0.4",
        "python-pptx==0.6.18",
        "pyyaml==5.3.1",
        "rdflib==5.0.0",
        "rdflib-sqlalchemy==0.4.0",
        "reportlab==3.5.56",
        "requests==2.25.0",
        "shapely==1.7.1",
        "six==1.15.0; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3'",
        "sqlalchemy==1.3.20; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3'",
        "svglib==1.0.1",
        "svgwrite==1.4",
        "tinycss2==1.1.0; python_version >= '3.6'",
        "tqdm==4.54.0",
        "urllib3==1.26.2; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3, 3.4' and python_version < '4'",
        "webencodings==0.5.1",
        "xlsxwriter==1.3.7",
    ],
    extras_require={"dev": []},
    dependency_links=[],
    project_urls={
        "Bug Reports": "https://github.com/dbrnz/flatmap-maker/issues",
        "Source": "https://github.com/dbrnz/flatmap-maker/",
    },
)

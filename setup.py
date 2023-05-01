import sys
import os
from setuptools import setup, find_packages

"""
This file should called to install the package.
"""

with open('requirements.txt') as f:
    required = f.read().splitlines()

# Call the setup process
setup(
    name = 'ragaz',
    version = "0.1.0-alpha",
    install_requires=required,
    packages = find_packages(),
    package_data = {
        '': ['README.md', 'LICENSE']},
    scripts=['ragazc'],
    description = 'Ragaz is a fast, safe and powerful pythonic language which aims allow you to create simple scripts to complex systems in a code easier to read, write and maintain than other system languages with the same purpose.',
    author='David Ragazzi',
    author_email='david_ragazzi@hotmail.com',
    url='https://github.com/ragazzi-robotics/ragaz/',
    classifiers=[
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Build Tools'
    ],
    long_description = """Ragaz is a fast, safe and powerful pythonic language which aims allow you to create simple scripts to complex systems in a code easier to read, write and maintain than other system languages with the same purpose.
For more information, see GitHub page (https://github.com/ragazzi-robotics/ragaz/)."""
)

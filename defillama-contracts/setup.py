#!/usr/bin/env python3
"""
Setup script for DefiLlama Contracts Library.
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README
readme_path = Path(__file__).parent / "README.md"
long_description = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

# Read requirements
requirements_path = Path(__file__).parent / "requirements.txt"
requirements = []
if requirements_path.exists():
    requirements = requirements_path.read_text().strip().split("\n")
    requirements = [r.strip() for r in requirements if r.strip() and not r.startswith("#")]

setup(
    name="defillama-contracts",
    version="1.0.0",
    author="Hermes Agent",
    author_email="hermeticsintellegencia@proton.me",
    description="A comprehensive Python library for interacting with 1,693 verified DefiLlama contracts across 49 chains",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/TerexitariusStomp/defillama-contracts",
    project_urls={
        "Bug Tracker": "https://github.com/TerexitariusStomp/defillama-contracts/issues",
        "Documentation": "https://github.com/TerexitariusStomp/defillama-contracts#readme",
        "Source Code": "https://github.com/TerexitariusStomp/defillama-contracts",
    },
    packages=find_packages(),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Intended Audience :: Financial and Insurance Industry",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Office/Business :: Financial",
        "Topic :: Internet :: WWW/HTTP",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "black>=23.0.0",
            "ruff>=0.0.280",
            "mypy>=1.0.0",
        ],
        "web3": [
            "web3>=6.0.0",
            "eth-abi>=4.0.0",
            "eth-utils>=2.0.0",
            "eth-account>=0.8.0",
        ],
        "full": [
            "web3>=6.0.0",
            "eth-abi>=4.0.0",
            "eth-utils>=2.0.0",
            "eth-account>=0.8.0",
            "requests>=2.28.0",
            "aiohttp>=3.8.0",
        ],
    },
    keywords=[
        "defi",
        "blockchain",
        "ethereum",
        "smart-contracts",
        "defillama",
        "dex",
        "bridge",
        "yield",
        "web3",
        "evm",
        "multi-chain",
    ],
    include_package_data=True,
    package_data={
        "": ["*.md", "*.txt", "*.json"],
    },
    entry_points={
        "console_scripts": [
            "defillama-contracts=defillama_contracts.cli:main",
        ],
    },
    zip_safe=False,
)